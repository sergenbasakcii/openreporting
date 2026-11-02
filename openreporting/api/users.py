"""User administration (admin) and self-service profile/preferences."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import folder_access
from ..db import audit, connect, transaction, utcnow
from ..security import authenticate, check_password, create_user, password_hash, reauthenticate
from ..timerange import TimeRangeError, zone
from .deps import admin, admin_read, settings_of, viewer_write

router = APIRouter()
ROLES = ("admin", "editor", "viewer")
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=14, max_length=256)
    role: str = "viewer"
    email: str = Field(default="", max_length=254)
    display_name: str = Field(default="", max_length=120)


class UserPatch(BaseModel):
    role: str | None = None
    active: bool | None = None
    email: str | None = Field(default=None, max_length=254)
    display_name: str | None = Field(default=None, max_length=120)


class PasswordReset(BaseModel):
    password: str = Field(min_length=14, max_length=256)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=14, max_length=256)


class MfaReset(BaseModel):
    reason: str
    password: str = Field(min_length=1, max_length=1024)


class PreferencesIn(BaseModel):
    theme: str = "dark"
    timezone: str = "browser"
    home_dashboard_uid: str | None = None


def _email(value):
    if value and not _EMAIL.match(value):
        raise HTTPException(422, "Geçersiz e-posta adresi")
    return value or ""


@router.get("/api/users")
def list_users(request: Request, user=Depends(admin_read)):
    with connect(settings_of(request)) as db:
        return [dict(r) for r in db.execute("""SELECT u.id,username,role,active,email,display_name,created_at,last_login_at,
                                               COALESCE(e.provider,'local') AS auth_provider,
                                               COALESCE(m.enabled,0) AS mfa_enabled
                                               FROM users u LEFT JOIN external_identities e ON e.user_id=u.id
                                               LEFT JOIN user_mfa m ON m.user_id=u.id ORDER BY username""")]


@router.post("/api/users", status_code=201)
def add_user(body: UserIn, request: Request, user=Depends(admin)):
    if body.role not in ROLES:
        raise HTTPException(422, "Geçersiz rol")
    settings = settings_of(request)
    with connect(settings) as db:
        if db.execute("SELECT 1 FROM users WHERE username=?", (body.username.strip().lower(),)).fetchone():
            raise HTTPException(409, "Bu kullanıcı adı zaten var")
    try:
        uid = create_user(settings, body.username, body.password, body.role)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with connect(settings) as db, transaction(db):
        db.execute("UPDATE users SET email=?,display_name=? WHERE id=?",
                   (_email(body.email), body.display_name.strip(), uid))
        audit(db, user["id"], "user.created_by_admin", "user", uid, {"role": body.role})
    return {"id": uid}


@router.patch("/api/users/{user_id}")
def update_user(user_id: str, body: UserPatch, request: Request, user=Depends(admin)):
    with connect(settings_of(request)) as db, transaction(db):
        target = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "Kullanıcı bulunamadı")
        external = db.execute("SELECT 1 FROM external_identities WHERE user_id=?", (user_id,)).fetchone()
        if external and body.role is not None:
            raise HTTPException(409, "LDAP rolleri dizin gruplarıyla yönetilir")
        role = body.role if body.role is not None else target["role"]
        active = int(body.active) if body.active is not None else target["active"]
        if role not in ROLES:
            raise HTTPException(422, "Geçersiz rol")
        if target["role"] == "admin" and target["active"] and (role != "admin" or not active):
            admins = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
            if admins <= 1:
                raise HTTPException(409, "Son etkin yönetici devre dışı bırakılamaz veya rolü değiştirilemez")
            if not external:
                local_admins = db.execute("""SELECT COUNT(*) FROM users u WHERE role='admin' AND active=1
                                            AND NOT EXISTS(SELECT 1 FROM external_identities e WHERE e.user_id=u.id)""").fetchone()[0]
                if local_admins <= 1:
                    raise HTTPException(409, "Son yerel kurtarma yöneticisi korunmalıdır")
        if user_id == user["id"] and not active:
            raise HTTPException(409, "Kendi hesabınızı devre dışı bırakamazsınız")
        email = _email(body.email) if body.email is not None else target["email"]
        name = body.display_name.strip() if body.display_name is not None else target["display_name"]
        db.execute("UPDATE users SET role=?,active=?,email=?,display_name=? WHERE id=?",
                   (role, active, email, name, user_id))
        if not active or role != target["role"]:
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        audit(db, user["id"], "user.updated", "user", user_id, {"role": role, "active": bool(active)})
    return {"id": user_id, "role": role, "active": bool(active)}


@router.post("/api/users/{user_id}/password")
def reset_password(user_id: str, body: PasswordReset, request: Request, user=Depends(admin)):
    try:
        hashed = password_hash(body.password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with connect(settings_of(request)) as db, transaction(db):
        if db.execute("SELECT 1 FROM external_identities WHERE user_id=?", (user_id,)).fetchone():
            raise HTTPException(409, "LDAP parolası dizin hizmetinde değiştirilmelidir")
        if not db.execute("UPDATE users SET password_hash=? WHERE id=?", (hashed, user_id)).rowcount:
            raise HTTPException(404, "Kullanıcı bulunamadı")
        db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        audit(db, user["id"], "user.password_reset_by_admin", "user", user_id)
    return {"ok": True}


@router.post("/api/users/{user_id}/mfa/reset")
def reset_mfa(user_id: str, body: MfaReset, request: Request, user=Depends(admin)):
    """Admin recovery for a lost authenticator; the user enrolls again at next sign-in."""
    if body.reason not in {"lost-device", "compromise", "recovery"}:
        raise HTTPException(422, "Geçerli bir sıfırlama nedeni seçin")
    if user_id == user["id"]:
        raise HTTPException(409, "Kendi iki adımlı girişinizi Profil sayfasından yönetin")
    settings = settings_of(request)
    reauthenticate(settings, user, body.password)
    with connect(settings) as db, transaction(db):
        if not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
            raise HTTPException(404, "Kullanıcı bulunamadı")
        if not db.execute("DELETE FROM user_mfa WHERE user_id=?", (user_id,)).rowcount:
            raise HTTPException(409, "Bu kullanıcıda iki adımlı giriş kurulu değil")
        db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        audit(db, user["id"], "mfa.reset_by_admin", "user", user_id, {"reason": body.reason})
    return {"ok": True}


@router.get("/api/user")
def current_user(request: Request, user=Depends(authenticate)):
    with connect(settings_of(request)) as db:
        row = db.execute("""SELECT u.id,username,role,email,display_name,last_login_at,COALESCE(e.provider,'local') AS auth_provider
                            FROM users u LEFT JOIN external_identities e ON e.user_id=u.id WHERE u.id=?""",
                         (user["id"],)).fetchone()
        prefs = db.execute("SELECT theme,timezone,home_dashboard_uid FROM user_prefs WHERE user_id=?",
                           (user["id"],)).fetchone()
        if prefs and prefs["home_dashboard_uid"]:
            target = db.execute("SELECT folder_id FROM dashboards WHERE uid=?", (prefs["home_dashboard_uid"],)).fetchone()
            if not target or not folder_access.allowed(db, user, target["folder_id"]):
                prefs = {**dict(prefs), "home_dashboard_uid": None}
    return {**dict(row), "preferences": dict(prefs) if prefs else
            {"theme": "dark", "timezone": "browser", "home_dashboard_uid": None}}


@router.put("/api/user/preferences")
def update_preferences(body: PreferencesIn, request: Request, user=Depends(viewer_write)):
    if body.theme not in ("dark", "light", "system"):
        raise HTTPException(422, "Geçersiz tema")
    if body.timezone not in ("browser", "utc"):
        try:
            zone(body.timezone)
        except TimeRangeError as exc:
            raise HTTPException(422, str(exc)) from exc
    with connect(settings_of(request)) as db, transaction(db):
        if body.home_dashboard_uid and not db.execute("SELECT 1 FROM dashboards WHERE uid=?",
                                                      (body.home_dashboard_uid,)).fetchone():
            raise HTTPException(422, "Ana sayfa dashboard'u bulunamadı")
        if body.home_dashboard_uid:
            try:
                folder_access.require_dashboard(db, user, body.home_dashboard_uid)
            except HTTPException:
                raise HTTPException(422, "Ana sayfa dashboard'u bulunamadı") from None
        db.execute("""INSERT INTO user_prefs(user_id,theme,timezone,home_dashboard_uid,updated_at) VALUES(?,?,?,?,?)
                      ON CONFLICT(user_id) DO UPDATE SET theme=excluded.theme,timezone=excluded.timezone,
                      home_dashboard_uid=excluded.home_dashboard_uid,updated_at=excluded.updated_at""",
                   (user["id"], body.theme, body.timezone, body.home_dashboard_uid, utcnow()))
    return body.model_dump()


@router.put("/api/user/password")
def change_password(body: PasswordChange, request: Request, user=Depends(viewer_write)):
    settings = settings_of(request)
    with connect(settings) as db:
        if db.execute("SELECT 1 FROM external_identities WHERE user_id=?", (user["id"],)).fetchone():
            raise HTTPException(409, "LDAP parolası dizin hizmetinde değiştirilmelidir")
    # Shared step-up path: lockout counter and scrypt concurrency cap, never an unthrottled oracle.
    try:
        reauthenticate(settings, user, body.old_password)
    except HTTPException as exc:
        if exc.status_code == 403:
            raise HTTPException(403, "Mevcut parola hatalı") from None
        raise
    try:
        hashed = password_hash(body.new_password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    token = request.cookies.get("openreporting_session", "")
    from ..security import digest
    with connect(settings) as db, transaction(db):
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (hashed, user["id"]))
        db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user["id"], digest(token)))
        audit(db, user["id"], "user.password_changed", "user", user["id"])
    return {"ok": True}
