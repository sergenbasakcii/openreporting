"""Service accounts and API tokens for automation (CI, ticketing, dashboards-as-code).

A service account is a user whose password hash is the marker ``!service``: it can never sign in
interactively, its role is viewer or editor (never admin), and folder ACLs and the audit log treat it
like any other user. A token is ``ortk_<prefix>_<secret>``; only its SHA-256 is stored, it always
expires, and it is shown exactly once. Bearer requests skip CSRF (browsers never attach the header
automatically) but are refused on account, session, MFA and administration endpoints.
"""

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from .db import audit, connect, transaction, utcnow
from .security import digest

SERVICE_MARKER = "!service"
SERVICE_ROLES = ("viewer", "editor")
TOKEN_PATTERN = re.compile(r"^ortk_([a-z0-9]{8})_([A-Za-z0-9_-]{32,64})$")
MAX_DAYS = 365
LAST_USED_RESOLUTION = timedelta(minutes=5)
# Paths a token may never use: own-account, session and administration surfaces.
BLOCKED_PREFIXES = ("/api/user", "/api/session", "/api/logout", "/api/login", "/api/admin", "/api/users", "/api/audit")
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")


class TokenError(ValueError):
    """Invalid request for a service account or token (user-facing, Turkish)."""


def is_service(row):
    return bool(row) and row["password_hash"] == SERVICE_MARKER


def create_account(settings, actor, username, role, display_name=""):
    username = str(username or "").strip().lower()
    if not _USERNAME.match(username):
        raise TokenError("Servis hesabı adı 3-80 karakter; küçük harf, rakam, . _ - olmalı")
    if role not in SERVICE_ROLES:
        raise TokenError("Servis hesabı rolü İzleyici veya Editör olabilir (yönetici olamaz)")
    user_id = str(uuid.uuid4())
    with connect(settings) as db, transaction(db):
        if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            raise TokenError("Bu kullanıcı adı zaten kullanılıyor")
        db.execute(
            "INSERT INTO users(id,username,password_hash,role,display_name,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, username, SERVICE_MARKER, role, str(display_name or "")[:120], utcnow()),
        )
        audit(db, actor, "service_account.created", "user", user_id, {"role": role})
    return {"id": user_id, "username": username, "role": role}


def list_accounts(settings):
    with connect(settings) as db:
        accounts = [
            dict(r)
            for r in db.execute("SELECT id,username,role,active,display_name,created_at FROM users WHERE password_hash=? ORDER BY username", (SERVICE_MARKER,))
        ]
        for account in accounts:
            account["tokens"] = [
                dict(t)
                for t in db.execute(
                    """SELECT id,name,prefix,created_at,expires_at,last_used_at,revoked_at FROM api_tokens
                       WHERE user_id=? ORDER BY created_at DESC""",
                    (account["id"],),
                )
            ]
    return accounts


def _account(db, account_id):
    row = db.execute("SELECT * FROM users WHERE id=?", (account_id,)).fetchone()
    if not is_service(row):
        raise HTTPException(404, "Servis hesabı bulunamadı")
    return row


def update_account(settings, actor, account_id, *, role=None, active=None):
    with connect(settings) as db, transaction(db):
        _account(db, account_id)
        if role is not None:
            if role not in SERVICE_ROLES:
                raise TokenError("Servis hesabı rolü İzleyici veya Editör olabilir (yönetici olamaz)")
            db.execute("UPDATE users SET role=? WHERE id=?", (role, account_id))
        if active is not None:
            db.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, account_id))
        audit(db, actor, "service_account.updated", "user", account_id, {"role": role, "active": active})


def issue(settings, actor, account_id, name, days):
    name = str(name or "").strip()
    if not 2 <= len(name) <= 80 or any(ord(c) < 32 for c in name):
        raise TokenError("Anahtar adı 2-80 karakter olmalı")
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= MAX_DAYS:
        raise TokenError(f"Geçerlilik 1-{MAX_DAYS} gün olmalı")
    prefix = secrets.token_hex(4)
    token = f"ortk_{prefix}_{secrets.token_urlsafe(32)}"
    token_id = str(uuid.uuid4())
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")
    with connect(settings) as db, transaction(db):
        _account(db, account_id)
        db.execute(
            "INSERT INTO api_tokens(id,user_id,name,prefix,token_hash,created_by,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)",
            (token_id, account_id, name, prefix, digest(token), actor, utcnow(), expires),
        )
        audit(db, actor, "api_token.issued", "api_token", token_id, {"account": account_id, "prefix": prefix, "expires_at": expires})
    return {"id": token_id, "token": token, "prefix": prefix, "expires_at": expires}


def revoke(settings, actor, token_id):
    with connect(settings) as db, transaction(db):
        if not db.execute("UPDATE api_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (utcnow(), token_id)).rowcount:
            raise HTTPException(404, "Etkin API anahtarı bulunamadı")
        audit(db, actor, "api_token.revoked", "api_token", token_id)


def authenticate_bearer(settings, header, path):
    """Return the request principal for ``Authorization: Bearer ortk_…`` or raise 401/403."""
    token = header[7:].strip()
    if not TOKEN_PATTERN.match(token):
        raise HTTPException(401, "Geçersiz API anahtarı")
    if path.startswith(BLOCKED_PREFIXES):
        raise HTTPException(403, "API anahtarı bu uç için kullanılamaz")
    now = datetime.now(timezone.utc)
    with connect(settings) as db:
        row = db.execute(
            """SELECT t.id AS token_id,t.expires_at,t.revoked_at,t.last_used_at,u.id,u.username,u.role,u.active,u.password_hash
               FROM api_tokens t JOIN users u ON u.id=t.user_id WHERE t.token_hash=?""",
            (digest(token),),
        ).fetchone()
    if (
        not row
        or row["revoked_at"]
        or not row["active"]
        or not is_service(row)
        or row["role"] not in SERVICE_ROLES
        or datetime.fromisoformat(row["expires_at"]) <= now
    ):
        raise HTTPException(401, "API anahtarı geçersiz, süresi dolmuş veya iptal edilmiş")
    if not row["last_used_at"] or now - datetime.fromisoformat(row["last_used_at"]) >= LAST_USED_RESOLUTION:
        with connect(settings) as db, transaction(db):
            db.execute("UPDATE api_tokens SET last_used_at=? WHERE id=?", (now.isoformat(timespec="seconds"), row["token_id"]))
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "active": 1,
        "provider": None,
        "csrf_hash": None,
        "expires_at": row["expires_at"],
        "via": "token",
        "token_id": row["token_id"],
        "mfa_enrollment_required": False,
    }
