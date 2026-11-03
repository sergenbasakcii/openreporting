"""Encryption at rest for source credentials and bound TOTP seeds (Fernet).

The key lives in its own 0600 file outside SQLite (``OPENREPORTING_SECRET_KEY_FILE``
or ``<data_dir>/secret.key``). Secrets are write-only through the API: the
browser only ever learns *whether* a source secret is configured. TOTP setup
returns its own new seed once, under password reauthentication + CSRF.
"""

import base64
import hashlib
import json
import os
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

_lock = threading.Lock()
_cache: dict[str, Fernet | MultiFernet] = {}
KEYRING_FORMAT = "openreporting-fernet-keyring-v1"
MAX_KEYS = 8


class SecretError(RuntimeError):
    pass


def key_path(settings) -> Path:
    explicit = getattr(settings, "secret_key_file", "") or ""
    return Path(explicit) if explicit else settings.data_dir / "secret.key"


def key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def read_keys(path: Path) -> list[bytes]:
    """Legacy raw key or a bounded versioned ring, primary first. Never generate."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(16385)
        if len(raw) > 16384:
            raise ValueError("oversize")
        raw = raw.strip()
        if not raw.startswith(b"{"):
            Fernet(raw)
            return [base64.urlsafe_b64encode(base64.urlsafe_b64decode(raw))]

        def unique_object(pairs):
            result = dict(pairs)
            if len(result) != len(pairs):
                raise ValueError("duplicate fields")
            return result

        ring = json.loads(raw, object_pairs_hook=unique_object)
        if set(ring) != {"format", "keys"} or ring["format"] != KEYRING_FORMAT or not isinstance(ring["keys"], list) or not 1 <= len(ring["keys"]) <= MAX_KEYS:
            raise ValueError("invalid format")
        keys = []
        for row in ring["keys"]:
            if not isinstance(row, dict) or set(row) != {"id", "key"} or not isinstance(row["key"], str):
                raise ValueError("invalid key record")
            key = row["key"].encode("ascii")
            Fernet(key)
            if len(key) != 44 or base64.urlsafe_b64encode(base64.urlsafe_b64decode(key)) != key or row["id"] != key_id(key) or key in keys:
                raise ValueError("invalid identity")
            keys.append(key)
        return keys
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise SecretError("Secret key file unreadable or invalid") from None


def _fernet(settings) -> Fernet | MultiFernet:
    path = key_path(settings)
    cache_key = str(path)
    with _lock:
        if cache_key in _cache:
            return _cache[cache_key]
        if not path.exists():
            if os.getenv("OPENREPORTING_REQUIRE_KEY_FILE") == "true":
                # Multi-replica deployments share one provisioned key; a pod-local key would split them.
                raise SecretError(
                    f"Şifreleme anahtarı bulunamadı ({path}); bu kurulumda anahtar önceden sağlanmalı (Kubernetes Secret). Yeni anahtar üretilmedi."
                )
            if _has_encrypted_secrets(settings):
                # Generating a fresh key would silently orphan every stored credential.
                raise SecretError(f"Şifreleme anahtarı bulunamadı ({path}) ama şifreli kimlik bilgileri var; anahtarı yedekten geri yükleyin")
            path.parent.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key()
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            try:
                fd = os.open(path, flags, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(key)
        keys = read_keys(path)
        fernet = MultiFernet([Fernet(key) for key in keys]) if len(keys) > 1 else Fernet(keys[0])
        _cache[cache_key] = fernet
        return fernet


def _has_encrypted_secrets(settings):
    from .db import has_encrypted_secrets

    try:
        return has_encrypted_secrets(settings)
    except Exception as exc:
        raise SecretError("Şifreli kimlik bilgileri kontrol edilemedi; yeni anahtar oluşturulmadı. Veritabanı erişimini ve yedeğini kontrol edin.") from exc


def encrypt(settings, data: dict) -> str:
    clean = {k: v for k, v in (data or {}).items() if v not in (None, "")}
    if not clean:
        return ""
    return _fernet(settings).encrypt(json.dumps(clean, separators=(",", ":")).encode()).decode()


def decrypt(settings, token: str) -> dict:
    if not token:
        return {}
    try:
        return json.loads(_fernet(settings).decrypt(token.encode()))
    except (InvalidToken, ValueError) as exc:
        raise SecretError("Stored secret cannot be decrypted with the current key") from exc


def reset_cache():
    with _lock:
        _cache.clear()


def installation_key_path(settings) -> Path:
    """Installer preflight only: never replace a lost key beside existing state."""
    path = key_path(settings)
    if path.exists():
        read_keys(path)
    elif settings.database_url or settings.db_path.exists() or path.is_symlink():
        raise SecretError("Existing state requires its original encryption key; restore it before installation")
    return path.resolve()
