"""Encryption at rest for datasource credentials (Fernet: AES-128-CBC + HMAC).

The key lives in its own 0600 file outside SQLite (``OPENREPORTING_SECRET_KEY_FILE``
or ``<data_dir>/secret.key``). Secrets are write-only through the API: the
browser only ever learns *whether* a secret is configured.
"""
import json
import os
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_lock = threading.Lock()
_cache: dict[str, Fernet] = {}


class SecretError(RuntimeError):
    pass


def key_path(settings) -> Path:
    explicit = getattr(settings, "secret_key_file", "") or ""
    return Path(explicit) if explicit else settings.data_dir / "secret.key"


def _fernet(settings) -> Fernet:
    path = key_path(settings)
    cache_key = str(path)
    with _lock:
        if cache_key in _cache:
            return _cache[cache_key]
        if not path.exists():
            if _has_encrypted_secrets(settings):
                # Generating a fresh key would silently orphan every stored credential.
                raise SecretError(f"Şifreleme anahtarı bulunamadı ({path}) ama şifreli kimlik bilgileri var; "
                                  "anahtarı yedekten geri yükleyin")
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
        try:
            key = path.read_bytes().strip()
            fernet = Fernet(key)
        except (OSError, ValueError) as exc:
            raise SecretError(f"Secret key file unreadable or invalid: {path}") from exc
        _cache[cache_key] = fernet
        return fernet


def _has_encrypted_secrets(settings):
    import sqlite3
    db_path = settings.data_dir / "state.sqlite3"
    if not db_path.exists():
        return False
    try:
        with sqlite3.connect(db_path) as db:
            row = db.execute("SELECT 1 FROM datasources WHERE secure_json<>'' LIMIT 1").fetchone()
    except sqlite3.Error:
        return False
    return row is not None


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
