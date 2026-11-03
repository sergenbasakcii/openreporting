"""TOTP enrollment, one-use verification and recovery. No mail/SMS or external service."""

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
import pyotp
import segno

from .db import audit, connect, transaction, utcnow, schema_version, CURRENT_VERSION, verify_audit
from .domain import parse_utc
from . import lockout
from .secrets_store import decrypt, encrypt, SecretError
from .security import digest, reauthenticate

ENROLLMENT_PATHS = frozenset({"/api/session", "/api/session/csrf", "/api/logout", "/api/user/mfa", "/api/user/mfa/setup", "/api/user/mfa/confirm"})


MSG_CODE_REJECTED = "Doğrulama kodu kabul edilmedi; yeni bir kodla tekrar deneyin"
MSG_CODE_OR_RECOVERY_REJECTED = "Doğrulama kodu kabul edilmedi; yeni bir kod veya kullanılmamış kurtarma kodu deneyin"


class Unavailable(RuntimeError):
    pass


def now_seconds():
    return time.time()


def factor(db, user_id):
    return db.execute("SELECT * FROM user_mfa WHERE user_id=?", (user_id,)).fetchone()


def seed(settings, row):
    try:
        value = decrypt(settings, row["secret_json"])
        if (
            set(value) != {"type", "user_id", "secret"}
            or value["type"] != "mfa-totp-v1"
            or value["user_id"] != row["user_id"]
            or not re.fullmatch("[A-Z2-7]{32}", value["secret"])
        ):
            raise ValueError("Invalid bound factor")
        return value["secret"]
    except (SecretError, ValueError, TypeError, KeyError):
        raise Unavailable("Second-factor storage unavailable") from None


def recovery_hash(user_id, value):
    return hashlib.sha256(f"mfa-recovery-v1:{user_id}:{value}".encode("ascii")).hexdigest()


def new_recovery(user_id):
    raw = [secrets.token_hex(16) for _ in range(10)]
    return ["-".join(value[i : i + 8] for i in range(0, 32, 8)) for value in raw], json.dumps([recovery_hash(user_id, value) for value in raw])


def recovery_hashes(row):
    try:
        values = json.loads(row["recovery_hashes"])
        if not isinstance(values, list) or len(values) > 10 or any(not isinstance(v, str) or not re.fullmatch("[a-f0-9]{64}", v) for v in values):
            raise ValueError("Invalid recovery records")
        return values
    except (ValueError, TypeError, KeyError):
        raise Unavailable("Second-factor storage unavailable") from None


def consume(db, settings, user_id, code, *, pending=False, now=None):
    """Caller holds the application write transaction; CAS also prevents duplicate use."""
    row = factor(db, user_id)
    if row is None or (not row["enabled"] and not pending) or not isinstance(code, str):
        return False
    if pending and (row["enabled"] or parse_utc(row["pending_expires_at"]) <= datetime.now(timezone.utc)):
        return False
    value = code.strip()
    if re.fullmatch("[0-9]{6}", value):
        counter = int((now_seconds() if now is None else now) // 30)
        otp = pyotp.TOTP(seed(settings, row))
        match = None
        for offset in (-1, 0, 1):
            candidate = counter + offset
            if candidate >= 0 and candidate > row["last_counter"] and hmac.compare_digest(otp.at(candidate * 30), value):
                match = candidate
        if match is None:
            return False
        return bool(db.execute("UPDATE user_mfa SET last_counter=? WHERE user_id=? AND last_counter=?", (match, user_id, row["last_counter"])).rowcount)
    if pending:
        return False
    normalized = value.replace("-", "").lower()
    if not re.fullmatch("[a-f0-9]{32}", normalized):
        return False
    values = recovery_hashes(row)
    expected = recovery_hash(user_id, normalized)
    hits = [i for i, item in enumerate(values) if hmac.compare_digest(item, expected)]
    if not hits:
        return False
    del values[hits[0]]
    return bool(
        db.execute(
            "UPDATE user_mfa SET recovery_hashes=? WHERE user_id=? AND recovery_hashes=?", (json.dumps(values), user_id, row["recovery_hashes"])
        ).rowcount
    )


def status(settings, user):
    with connect(settings) as db:
        row = factor(db, user["id"])
        enabled = bool(row and row["enabled"])
        return {"enabled": enabled, "recovery_remaining": len(recovery_hashes(row)) if enabled else 0, "required": user["role"] in settings.mfa_required_roles}


def _snapshot_matches(db, snapshot):
    row = db.execute(
        """SELECT u.id,u.username,u.active,u.role,u.password_hash,e.subject FROM users u
        LEFT JOIN external_identities e ON e.user_id=u.id WHERE u.id=?""",
        (snapshot["id"],),
    ).fetchone()
    if not row or not row["active"] or any(row[key] != snapshot[key] for key in ("username", "role", "password_hash", "subject")):
        raise HTTPException(409, "Hesap bilgileri değişti; yeniden giriş yapın")


class _Attempt:
    """Outcome of a proof checked inside :func:`_step_up`."""

    def __init__(self):
        self.failed = None  # None: no proof checked; True/False after verify()

    def verify(self, ok):
        self.failed = not ok
        return ok


@contextmanager
def _step_up(settings, user, password, failure_message):
    """Re-authenticated, lockout-gated write transaction for changes to the user's own factor.

    The body reports a checked code with ``attempt.verify(ok)``. A failure is counted in the same
    transaction and the 403 is raised only after it commits, so the counter always persists.
    """
    snapshot = reauthenticate(settings, user, password)
    keys = lockout.failure_keys(user["username"], step_up=True)
    attempt = _Attempt()
    with connect(settings) as db, transaction(db):
        _snapshot_matches(db, snapshot)
        lockout.gate(db, keys)
        yield db, attempt
        if attempt.failed:
            lockout.record_failure(db, keys)
        elif attempt.failed is False:
            lockout.clear_failures(db, keys)
    if attempt.failed:
        raise HTTPException(403, failure_message)


def start_setup(settings, user, password):
    secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii")
    setup_token = secrets.token_urlsafe(32)
    sealed = encrypt(settings, {"type": "mfa-totp-v1", "user_id": user["id"], "secret": secret})
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(timespec="seconds")
    with _step_up(settings, user, password, MSG_CODE_REJECTED) as (db, _):
        row = factor(db, user["id"])
        if row and row["enabled"]:
            raise HTTPException(409, "İki adımlı giriş zaten etkin")
        db.execute(
            """INSERT INTO user_mfa(user_id,secret_json,pending_expires_at,setup_hash,updated_at) VALUES(?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET secret_json=excluded.secret_json,pending_expires_at=excluded.pending_expires_at,
            setup_hash=excluded.setup_hash,last_counter=-1,recovery_hashes='[]',updated_at=excluded.updated_at""",
            (user["id"], sealed, expires, digest(setup_token), utcnow()),
        )
        audit(db, user["id"], "mfa.setup_started", "user", user["id"])
    uri = pyotp.TOTP(secret).provisioning_uri(name=user["username"], issuer_name="OpenReporting")
    return {"secret": secret, "setup_token": setup_token, "expires_at": expires, "uri": uri, "qr": qr_data_uri(uri)}


def qr_data_uri(uri):
    """Enrollment QR as an inline SVG data URI: rendered on the server, nothing leaves this response.

    Dark modules on an explicit white quiet zone so phone cameras read it on the dark theme too.
    """
    return segno.make(uri, error="m", micro=False).svg_data_uri(scale=5, border=4, dark="#000000", light="#ffffff")


def confirm_setup(settings, user, password, code, setup_token):
    codes = None
    with _step_up(settings, user, password, MSG_CODE_REJECTED) as (db, attempt):
        row = factor(db, user["id"])
        if (
            not row
            or row["enabled"]
            or not hmac.compare_digest(row["setup_hash"], digest(setup_token))
            or parse_utc(row["pending_expires_at"]) <= datetime.now(timezone.utc)
        ):
            raise HTTPException(409, "Kurulum süresi doldu veya değişti; baştan başlayın")
        if attempt.verify(consume(db, settings, user["id"], code, pending=True)):
            codes, hashes = new_recovery(user["id"])
            db.execute(
                "UPDATE user_mfa SET enabled=1,pending_expires_at='',setup_hash='',recovery_hashes=?,updated_at=? WHERE user_id=?",
                (hashes, utcnow(), user["id"]),
            )
            db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            audit(db, user["id"], "mfa.enabled", "user", user["id"])
    return {"enabled": True, "recovery_codes": codes, "sign_in_required": True}


def manage(settings, user, password, code, *, disable=False):
    codes = None
    with _step_up(settings, user, password, MSG_CODE_OR_RECOVERY_REJECTED) as (db, attempt):
        row = factor(db, user["id"])
        if not row or not row["enabled"]:
            raise HTTPException(409, "İki adımlı giriş etkin değil")
        if attempt.verify(consume(db, settings, user["id"], code)):
            if disable:
                db.execute("DELETE FROM user_mfa WHERE user_id=?", (user["id"],))
            else:
                codes, hashes = new_recovery(user["id"])
                db.execute("UPDATE user_mfa SET recovery_hashes=?,updated_at=? WHERE user_id=?", (hashes, utcnow(), user["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            audit(db, user["id"], "mfa.disabled" if disable else "mfa.recovery_rotated", "user", user["id"])
    return {"enabled": not disable, "recovery_codes": codes, "sign_in_required": True}


@contextmanager
def _existing_store(settings):
    if settings.database_url:
        with connect(settings) as db:
            yield db
    else:
        # mode=rw closes the exists/connect race without ever making a replacement DB.
        with closing(sqlite3.connect(settings.db_path.resolve().as_uri() + "?mode=rw", uri=True, timeout=20)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            yield db


def admin_reset(settings, username, reason):
    if reason not in {"lost-device", "compromise", "recovery"}:
        raise ValueError("A supported reset reason is required")
    if not settings.database_url and not settings.db_path.is_file():
        raise ValueError("Existing application database is required")
    with _existing_store(settings) as db, transaction(db):
        if schema_version(db) != CURRENT_VERSION or not verify_audit(db)[0]:
            raise ValueError("Matching application schema is required; no migration performed")
        row = db.execute("SELECT id FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
        if not row:
            raise ValueError("User not found")
        db.execute("DELETE FROM user_mfa WHERE user_id=?", (row["id"],))
        db.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
        audit(db, "os-admin", "mfa.reset_by_operator", "user", row["id"], {"reason": reason})
    return {"reset": True, "sign_in_required": True}
