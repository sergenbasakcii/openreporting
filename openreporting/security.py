"""Cookie sessions, scrypt password hashes, CSRF and role controls."""

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from psycopg import Error as PostgresError

from .db import connect, transaction, utcnow, audit

# Bound expensive unauthenticated scrypt/LDAP work before opening the state store.
# Per-process admission supplements the reverse proxy's IP rate limits.
AUTH_CONCURRENCY = 4
_auth_slots = threading.BoundedSemaphore(AUTH_CONCURRENCY)
AUTH_SLOT_WAIT_S = 3


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password: str) -> str:
    if len(password) < 14:
        raise ValueError("Password must contain at least 14 characters")
    salt = os.urandom(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)
    return f"scrypt$32768$8$1${salt.hex()}${derived.hex()}"


def check_password(password: str, encoded: str) -> bool:
    try:
        name, n, r, p, salt, expected = encoded.split("$")
        if name != "scrypt" or (int(n), int(r), int(p)) != (32768, 8, 1):
            return False
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(candidate, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def create_user(settings, username, password, role="admin"):
    if role not in {"admin", "editor", "viewer"}:
        raise ValueError("Unknown role")
    username = username.strip().lower()
    if not (3 <= len(username) <= 80) or not username.replace("_", "").replace(".", "").isalnum():
        raise ValueError("Invalid username")
    uid = str(uuid.uuid4())
    with connect(settings) as db, transaction(db):
        db.execute("INSERT INTO users(id,username,password_hash,role,created_at) VALUES(?,?,?,?,?)", (uid, username, password_hash(password), role, utcnow()))
        audit(db, "bootstrap", "user.create", "user", uid, {"role": role})
    return uid


# Lockout policy lives in its own module; names re-exported for existing callers.
from .lockout import LOCK_WINDOW, PAIR_LIMIT, USER_LIMIT, clear_failures, failure_keys, record_failure  # noqa: E402,F401
from .lockout import gate as _login_gate  # noqa: E402
from . import messages


def reauthenticate(settings, user, password):
    """Step-up primary credential check; never issue a session or clear OTP failures."""
    from . import directory_auth

    if not _auth_slots.acquire(timeout=AUTH_SLOT_WAIT_S):
        raise HTTPException(429, messages.AUTH_BUSY, headers={"Retry-After": "1"})
    try:
        with connect(settings) as db, transaction(db):
            _login_gate(db, failure_keys(user["username"], step_up=True))
            row = db.execute(
                """SELECT u.id,u.username,u.active,u.role,u.password_hash,e.subject FROM users u
                LEFT JOIN external_identities e ON e.user_id=u.id WHERE u.id=?""",
                (user["id"],),
            ).fetchone()
            snapshot = dict(row) if row else None
        valid = bool(snapshot and snapshot["active"] and snapshot["role"] == user["role"])
        if valid and snapshot["subject"] is None:
            valid = check_password(password, snapshot["password_hash"])
        elif valid:
            try:
                identity = directory_auth.authenticate(settings, snapshot["username"], password)
            except directory_auth.DirectoryUnavailable:
                raise HTTPException(503, messages.DIRECTORY_UNAVAILABLE) from None
            valid = bool(identity and identity.subject == snapshot["subject"] and identity.role == snapshot["role"])
        if not valid:
            with connect(settings) as db, transaction(db):
                keys = failure_keys(user["username"], step_up=True)
                _login_gate(db, keys)
                record_failure(db, keys)
            raise HTTPException(403, "Parola doğrulanamadı")
        return snapshot
    except (sqlite3.Error, PostgresError, OSError):
        raise HTTPException(503, messages.AUTH_STORAGE_UNAVAILABLE) from None
    finally:
        _auth_slots.release()


def login(settings, username: str, password: str, otp: str | None = None, client: str | None = None):
    if not _auth_slots.acquire(timeout=AUTH_SLOT_WAIT_S):
        raise HTTPException(429, messages.AUTH_BUSY, headers={"Retry-After": "1"})
    try:
        return _login(settings, username, password, otp, client)
    except (sqlite3.Error, PostgresError, OSError):
        raise HTTPException(503, messages.AUTH_STORAGE_UNAVAILABLE) from None
    finally:
        _auth_slots.release()


def _login(settings, username: str, password: str, otp: str | None = None, client: str | None = None):
    from . import directory_auth, mfa

    username = username.strip().lower()
    keys = failure_keys(username, client)
    # Do not hold the application write lock during directory/network operations.
    with connect(settings) as db, transaction(db):
        _login_gate(db, keys)
        existing = db.execute("SELECT u.*,e.subject FROM users u LEFT JOIN external_identities e ON e.user_id=u.id WHERE u.username=?", (username,)).fetchone()
        existing = dict(existing) if existing else None
    identity = None
    is_local = existing and existing["subject"] is None
    if is_local:
        password_ok = check_password(password, existing["password_hash"])  # always pay the hash cost
        valid = bool(existing["active"]) and password_ok
    elif existing and not existing["active"]:
        check_password(password, DUMMY_HASH)
        valid = False
    else:
        try:
            identity = directory_auth.authenticate(settings, username, password)
        except directory_auth.DirectoryUnavailable:
            raise HTTPException(503, messages.DIRECTORY_UNAVAILABLE) from None
        valid = identity is not None
        if not settings.ldap_enabled:
            check_password(password, DUMMY_HASH)
    failure = False
    challenge = False
    with connect(settings) as db, transaction(db):
        _login_gate(db, keys)
        user = db.execute("SELECT u.*,e.subject FROM users u LEFT JOIN external_identities e ON e.user_id=u.id WHERE u.username=?", (username,)).fetchone()
        if is_local:
            valid = valid and user is not None and user["active"] and user["subject"] is None and user["password_hash"] == existing["password_hash"]
        elif valid:
            # A local username can never be taken over by a directory identity.
            if user:
                valid = bool(user["active"]) and user["subject"] == identity.subject
            elif db.execute("SELECT 1 FROM external_identities WHERE provider='ldap' AND subject=?", (identity.subject,)).fetchone():
                valid = False  # Directory rename needs explicit operator reconciliation.
            else:
                uid = str(uuid.uuid4())
                db.execute(
                    "INSERT INTO users(id,username,password_hash,role,email,display_name,created_at) VALUES(?,?,?,?,?,?,?)",
                    (uid, username, "!ldap", identity.role, identity.email, identity.display_name, utcnow()),
                )
                db.execute("INSERT INTO external_identities(user_id,provider,subject) VALUES(?,'ldap',?)", (uid, identity.subject))
                audit(db, uid, "user.directory_provisioned", "user", uid, {"role": identity.role})
                user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if valid:
                if user["role"] != identity.role:
                    db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
                    audit(db, user["id"], "user.directory_role_changed", "user", user["id"], {"role": identity.role})
                db.execute("UPDATE users SET role=?,email=?,display_name=? WHERE id=?", (identity.role, identity.email, identity.display_name, user["id"]))
        factor_verified = False
        active_factor = mfa.factor(db, user["id"]) if valid else None
        if active_factor and active_factor["enabled"]:
            if not otp:
                challenge = True
            else:
                try:
                    factor_verified = mfa.consume(db, settings, user["id"], otp)
                except mfa.Unavailable:
                    raise HTTPException(503, messages.FACTOR_STORAGE_UNAVAILABLE) from None
                valid = valid and factor_verified
        if challenge:
            pass  # Commit verified directory role reductions/revocations, but never mint a session.
        elif not valid:
            record_failure(db, keys, client)
            failure = True
        else:
            clear_failures(db, keys)
            token = secrets.token_urlsafe(48)
            csrf = secrets.token_urlsafe(32)
            minutes = settings.session_hours * 60
            if identity:
                minutes = min(minutes, settings.ldap_session_minutes)
            role = identity.role if identity else user["role"]
            if role in settings.mfa_required_roles and not (active_factor and active_factor["enabled"]):
                minutes = min(minutes, 10)
            expiry = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(timespec="seconds")
            db.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", (digest(token), user["id"], digest(csrf), expiry, utcnow()))
            if factor_verified:
                db.execute("INSERT INTO mfa_sessions(token_hash) VALUES(?)", (digest(token),))
            db.execute("UPDATE users SET last_login_at=? WHERE id=?", (utcnow(), user["id"]))
            db.execute("DELETE FROM sessions WHERE expires_at<?", (utcnow(),))
            audit(db, user["id"], "auth.login", "session", "redacted", {"provider": "ldap" if identity else "local"})
    if challenge:
        raise HTTPException(401, {"code": "mfa_required", "message": "Ek doğrulama gerekli"})
    if failure:
        raise HTTPException(401, "Kullanıcı adı veya parola hatalı")
    return token, csrf, expiry


def authenticate(request: Request):
    token = request.cookies.get("openreporting_session")
    if not token:
        raise HTTPException(401, "Giriş yapmanız gerekiyor")
    from .runtime_settings import effective

    settings = effective(request.app.state.settings)
    try:
        with connect(settings) as db:
            row = db.execute(
                """SELECT u.id,u.username,u.role,u.active,s.csrf_hash,s.expires_at,s.created_at,e.provider,
                m.enabled AS mfa_enabled,ms.token_hash AS factor_session
                FROM sessions s JOIN users u ON u.id=s.user_id LEFT JOIN external_identities e ON e.user_id=u.id
                LEFT JOIN user_mfa m ON m.user_id=u.id LEFT JOIN mfa_sessions ms ON ms.token_hash=s.token_hash
                WHERE s.token_hash=?""",
                (digest(token),),
            ).fetchone()
    except (sqlite3.Error, PostgresError, OSError):
        raise HTTPException(503, messages.AUTH_STORAGE_UNAVAILABLE) from None
    if (
        not row
        or not row["active"]
        or (row["provider"] == "ldap" and not settings.ldap_enabled)
        or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc)
    ):
        raise HTTPException(401, "Oturum süresi doldu; tekrar giriş yapın")
    if row["mfa_enabled"] and not row["factor_session"]:
        raise HTTPException(401, "Ek doğrulama gerekli")
    required = row["role"] in settings.mfa_required_roles and not row["mfa_enabled"]
    if required:
        if datetime.fromisoformat(row["created_at"]) <= datetime.now(timezone.utc) - timedelta(minutes=10):
            raise HTTPException(401, "Kurulum oturumunun süresi doldu; tekrar giriş yapın")
        from .mfa import ENROLLMENT_PATHS

        if request.scope["path"] not in ENROLLMENT_PATHS:
            raise HTTPException(403, {"code": "mfa_enrollment_required", "message": "Complete second-factor enrollment first"})
    return {**dict(row), "mfa_enrollment_required": bool(required)}


def require_role(user, *roles):
    if user["role"] not in roles:
        raise HTTPException(403, "Bu işlem için yetkiniz yok")


def require_csrf(request: Request, user):
    header = request.headers.get("X-CSRF-Token", "")
    if not header or not hmac.compare_digest(digest(header), user["csrf_hash"]):
        raise HTTPException(403, messages.CSRF_FAILED)
    # X-CSRF-Token is non-simple; CORS is deliberately not enabled.


def logout(settings, token: str):
    if token:
        with connect(settings) as db, transaction(db):
            db.execute("DELETE FROM sessions WHERE token_hash=?", (digest(token),))


# Constant, valid scrypt hash used for unknown accounts only.
DUMMY_HASH = password_hash("not-a-real-credential-used-for-dummy")
