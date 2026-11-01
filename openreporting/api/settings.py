"""Admin UI for runtime settings (SMTP, LDAP, security policy, limits, source policy)."""
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import runtime_settings
from ..db import audit, connect, transaction
from ..security import reauthenticate
from .deps import admin, admin_read, settings_of

router = APIRouter()


class ScopeSave(BaseModel):
    revision: int = Field(ge=0)
    values: dict = Field(default_factory=dict)
    secrets: dict = Field(default_factory=dict)
    password: str = Field(min_length=1, max_length=1024)


class ScopeReset(BaseModel):
    revision: int = Field(ge=0)
    password: str = Field(min_length=1, max_length=1024)


class ScopeTest(BaseModel):
    values: dict = Field(default_factory=dict)
    secrets: dict = Field(default_factory=dict)


def _scope(scope):
    if scope not in runtime_settings.SCOPES:
        raise HTTPException(404, "Ayar bölümü bulunamadı")
    return scope


def _server_info(base):
    """Process-level settings: shown read-only because changing them needs a service restart."""
    from ..secrets_store import key_path
    rows = [
        ("Genel adres", "OPENREPORTING_PUBLIC_URL", base.public_url or "—"),
        ("Ek host adları", "OPENREPORTING_ALLOWED_HOSTS", ", ".join(base.allowed_hosts) or "—"),
        ("Güvenli çerez (yalnız HTTPS)", "OPENREPORTING_COOKIE_SECURE", "açık" if base.secure_cookie else "kapalı"),
        ("Web işçi süreci", "OPENREPORTING_WEB_WORKERS", os.getenv("OPENREPORTING_WEB_WORKERS", "2")),
        ("Ters vekil başlıkları", "OPENREPORTING_PROXY_HEADERS", os.getenv("OPENREPORTING_PROXY_HEADERS", "false")),
        ("Veri dizini", "OPENREPORTING_DATA_DIR", str(base.data_dir)),
        ("Uygulama veritabanı", "OPENREPORTING_DATABASE_URL", "PostgreSQL (deneysel)" if base.database_url else "SQLite"),
        ("Şifreleme anahtarı dosyası", "OPENREPORTING_SECRET_KEY_FILE", str(key_path(base))),
        ("SMTP CA dosyası", "OPENREPORTING_SMTP_CA_FILE", base.smtp_ca_file or "—"),
        ("LDAP CA dosyası", "OPENREPORTING_LDAP_CA_FILE", base.ldap_ca_file or "—"),
        ("Sentetik TestData kaynağı", "OPENREPORTING_PROVISION_TESTDATA", "açık" if base.provision_testdata else "kapalı"),
    ]
    return [{"label": label, "env": env, "value": value} for label, env, value in rows]


@router.get("/api/admin/settings")
def read_settings(request: Request, user=Depends(admin_read)):
    base = request.app.state.settings
    return {"scopes": runtime_settings.admin_view(base), "server": _server_info(base),
            "env_file": "/etc/openreporting/openreporting.env" if os.name != "nt" else "windows\Settings.local.ps1",
            "restart": ("sudo systemctl restart openreporting-web openreporting-worker" if os.name != "nt"
                        else "Start-OpenReporting.ps1 penceresini kapatıp yeniden çalıştırın")}


def _guard_self_lockout(settings, user, scope, values):
    if scope != "ldap" or values.get("ldap_enabled", True):
        return
    with connect(settings) as db:
        ldap_user = db.execute("SELECT 1 FROM external_identities WHERE user_id=?", (user["id"],)).fetchone()
    if ldap_user:
        raise HTTPException(409, "LDAP ile giriş yaptığınız için LDAP'ı kapatamazsınız; yerel bir yönetici hesabıyla yapın")


@router.put("/api/admin/settings/{scope}")
def save_settings(scope: str, body: ScopeSave, request: Request, user=Depends(admin)):
    settings = settings_of(request)
    _scope(scope)
    _guard_self_lockout(settings, user, scope, body.values)
    reauthenticate(settings, user, body.password)
    try:
        runtime_settings.save(request.app.state.settings, scope, body.values, body.secrets, body.revision, user["id"])
    except runtime_settings.SettingsConflict:
        raise HTTPException(409, "Ayarlar bu arada başka biri tarafından değiştirildi; sayfayı yenileyin") from None
    except ValueError as exc:
        raise HTTPException(422, runtime_settings.message(exc)) from None
    return runtime_settings.admin_view(request.app.state.settings)[scope]


@router.post("/api/admin/settings/{scope}/reset")
def reset_settings(scope: str, body: ScopeReset, request: Request, user=Depends(admin)):
    settings = settings_of(request)
    _scope(scope)
    _guard_self_lockout(settings, user, scope, {"ldap_enabled": request.app.state.settings.ldap_enabled})
    reauthenticate(settings, user, body.password)
    try:
        runtime_settings.reset(request.app.state.settings, scope, body.revision, user["id"])
    except runtime_settings.SettingsConflict:
        raise HTTPException(409, "Ayarlar bu arada başka biri tarafından değiştirildi; sayfayı yenileyin") from None
    except ValueError as exc:
        raise HTTPException(422, "Sunucu dosyasındaki değerler geçersiz: " + runtime_settings.message(exc)) from None
    return runtime_settings.admin_view(request.app.state.settings)[scope]


@router.post("/api/admin/settings/{scope}/test")
def test_settings(scope: str, body: ScopeTest, request: Request, user=Depends(admin)):
    """Try the form values before saving. Nothing is stored; SMTP never sends a message."""
    from .. import directory_auth, mail_transport
    if _scope(scope) not in runtime_settings.FAIL_CLOSED:
        raise HTTPException(404, "Bu bölüm için bağlantı testi yok")
    try:
        candidate = runtime_settings.test_candidate(request.app.state.settings, scope, body.values, body.secrets)
    except ValueError as exc:
        raise HTTPException(422, runtime_settings.message(exc)) from None
    try:
        check = directory_auth.check_connection if scope == "ldap" else mail_transport.check_connection
        message, ok = check(candidate), True
    except Exception:  # Never expose directory/SMTP responses, challenges or secrets.
        message, ok = "Bağlantı doğrulanamadı. Sunucu adı, port, sertifika ve hesap bilgilerini kontrol edin.", False
    with connect(settings_of(request)) as db, transaction(db):
        audit(db, user["id"], "integration.checked", "integration", "ldap" if scope == "ldap" else "smtp",
              {"ok": ok, "unsaved": True})
    return {"ok": ok, "message": message}
