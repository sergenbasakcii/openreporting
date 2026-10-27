"""Cookie sessions, scrypt password hashes, CSRF and role controls."""
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from .db import connect, transaction, utcnow, audit


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password: str) -> str:
    if len(password) < 14:
        raise ValueError("Password must contain at least 14 characters")
    salt = os.urandom(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=1, dklen=32, maxmem=64*1024*1024)
    return f"scrypt$32768$8$1${salt.hex()}${derived.hex()}"


def check_password(password: str, encoded: str) -> bool:
    try:
        name, n, r, p, salt, expected = encoded.split("$")
        if name != "scrypt" or (int(n), int(r), int(p)) != (32768, 8, 1):
            return False
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32, maxmem=64*1024*1024)
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


def login(settings, username: str, password: str):
    username = username.strip().lower()
    failure = False
    with connect(settings) as db, transaction(db):
        failures = db.execute("SELECT count,last_at FROM login_failures WHERE username=?", (username,)).fetchone()
        if failures and failures["count"] >= 5:
            last = datetime.fromisoformat(failures["last_at"])
            if datetime.now(timezone.utc) - last < timedelta(minutes=15):
                raise HTTPException(429, "Too many attempts; retry after 15 minutes")
            db.execute("DELETE FROM login_failures WHERE username=?", (username,))
        user = db.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        # Consume similar work for unknown accounts to reduce enumeration side channels.
        valid = check_password(password, user["password_hash"] if user else DUMMY_HASH)
        if not user or not valid:
            db.execute("INSERT INTO login_failures(username,count,last_at) VALUES(?,1,?) ON CONFLICT(username) DO UPDATE SET count=count+1,last_at=excluded.last_at", (username, utcnow()))
            audit(db, "anonymous", "auth.failed", "login", "redacted")
            failure = True
        else:
            db.execute("DELETE FROM login_failures WHERE username=?", (username,))
            token = secrets.token_urlsafe(48)
            csrf = secrets.token_urlsafe(32)
            expiry = (datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)).isoformat(timespec="seconds")
            db.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", (digest(token), user["id"], digest(csrf), expiry, utcnow()))
            db.execute("UPDATE users SET last_login_at=? WHERE id=?", (utcnow(), user["id"]))
            db.execute("DELETE FROM sessions WHERE expires_at<?", (utcnow(),))
            audit(db, user["id"], "auth.login", "session", "redacted")
    if failure:
        raise HTTPException(401, "Invalid credentials")
    return token, csrf, expiry


def authenticate(request: Request):
    token = request.cookies.get("openreporting_session")
    if not token:
        raise HTTPException(401, "Login required")
    settings = request.app.state.settings
    with connect(settings) as db:
        row = db.execute("""SELECT u.id,u.username,u.role,u.active,s.csrf_hash,s.expires_at
            FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?""", (digest(token),)).fetchone()
    if not row or not row["active"] or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        raise HTTPException(401, "Session expired")
    return dict(row)


def require_role(user, *roles):
    if user["role"] not in roles:
        raise HTTPException(403, "Insufficient permissions")


def require_csrf(request: Request, user):
    header = request.headers.get("X-CSRF-Token", "")
    if not header or not hmac.compare_digest(digest(header), user["csrf_hash"]):
        raise HTTPException(403, "CSRF validation failed")
    # X-CSRF-Token is non-simple; CORS is deliberately not enabled.


def logout(settings, token: str):
    if token:
        with connect(settings) as db, transaction(db):
            db.execute("DELETE FROM sessions WHERE token_hash=?", (digest(token),))


# Constant, valid scrypt hash used for unknown accounts only.
DUMMY_HASH = password_hash("not-a-real-credential-used-for-dummy")
