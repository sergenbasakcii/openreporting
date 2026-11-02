import logging
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .db import connect, init_db, transaction, verify_audit
from .domain import DomainError
from .healthchecks import database_ready
from .request_limits import RequestBodyLimitMiddleware
from .http_security import OriginValidationMiddleware, trusted_hosts
from .http_telemetry import HttpMetrics, HttpTelemetryMiddleware
from .security import authenticate, digest, login, logout, require_csrf, require_role
from .api.deps import settings_of

log = logging.getLogger(__name__)

SESSION_COOKIE = "openreporting_session"
SPA_PREFIXES = ("d/", "dashboards", "dashboard/", "explore", "datasources", "reports", "admin", "profile",
                "login", "playlists", "alerting")


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(max_length=1024)
    otp: str | None = Field(default=None,max_length=128)


def create_app(settings: Settings | None = None):
    from . import __version__, datasources as datasource_registry
    from .api import dashboards as dashboards_api, datasources as datasources_api, reports as reports_api
    from .api import system as system_api, users as users_api, mfa as mfa_api, settings as settings_api

    settings = settings or Settings.from_env()
    init_db(settings)
    datasource_registry.provision(settings)
    app = FastAPI(title="OpenReporting", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.http_metrics = HttpMetrics()
    static = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")
    for module in (datasources_api, dashboards_api, users_api, reports_api, system_api, mfa_api, settings_api):
        app.include_router(module.router)
    app.add_middleware(RequestBodyLimitMiddleware)
    app.add_middleware(OriginValidationMiddleware)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=trusted_hosts(settings),www_redirect=False)

    @app.middleware("http")
    async def headers(request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            # Request contents and exception messages can contain credentials.
            # The correlated HTTP 500 event is emitted by the outer telemetry layer.
            response = JSONResponse({'detail': 'Internal server error'}, status_code=500)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = ("default-src 'self'; object-src 'none'; base-uri 'none'; "
                                                       "frame-ancestors 'none'; style-src 'self' 'unsafe-inline'; script-src 'self'; "
                                                       "img-src 'self' data: blob:; form-action 'self'")
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if settings.secure_cookie:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        path = request.scope.get("path", "")
        if path.startswith("/static/") and not path.endswith((".html",)):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.exception_handler(DomainError)
    async def domain_exception(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (static / "index.html").read_text(encoding="utf8")

    @app.get("/healthz")
    def health():
        return {"status": "up"}

    @app.get("/readyz")
    def ready(request: Request, user=Depends(authenticate)):
        require_role(user, "admin")
        settings = settings_of(request)
        database_ok, audit_ok, broken_id = False, None, None
        try:
            with connect(settings) as db:
                database_ok = database_ready(db)
                if database_ok:
                    audit_ok, broken_id = verify_audit(db)
        except Exception:  # A readiness probe must not expose storage exception details.
            database_ok = False
        return JSONResponse({"state_database": "ready" if database_ok else "unavailable", "audit_chain_valid": audit_ok,
                             "audit_broken_id": broken_id, "mail_enabled": settings.mail_enabled},
                            status_code=200 if database_ok and audit_ok else 503)

    @app.post("/api/login")
    def sign_in(body: Credentials, request: Request,response: Response):
        if body.otp:
            mfa_api.ensure_transport(request)
        settings = settings_of(request)
        token, csrf, expiry = login(settings, body.username, body.password, body.otp, request.client.host if request.client else None)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=settings.secure_cookie,
                            samesite="strict", max_age=settings.session_hours * 3600, path="/")
        return {"csrf": csrf, "expires_at": expiry}

    @app.post("/api/logout")
    def sign_out(request: Request, response: Response, user=Depends(authenticate)):
        require_csrf(request, user)
        logout(settings_of(request), request.cookies.get(SESSION_COOKIE))
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/session")
    def session(user=Depends(authenticate)):
        # The CSRF token is minted on login and held in JS memory. A tab reload
        # logs the user into the same cookie session via a CSRF rotation endpoint.
        return {"user": {"id": user["id"], "username": user["username"], "role": user["role"]},
                "expires_at": user["expires_at"],'mfa_enrollment_required':user['mfa_enrollment_required']}

    @app.post("/api/session/csrf")
    def csrf_refresh(request: Request, user=Depends(authenticate)):
        # Require same-origin browser signal; no CSRF-bearing mutation is made here
        # other than rotating a token for an already authenticated session.
        if request.headers.get("Sec-Fetch-Site") not in ("same-origin", "none"):
            raise HTTPException(403, "Same-origin request required")
        csrf = secrets.token_urlsafe(32)
        token = request.cookies.get(SESSION_COOKIE)
        with connect(settings_of(request)) as db, transaction(db):
            db.execute("UPDATE sessions SET csrf_hash=? WHERE token_hash=?", (digest(csrf), digest(token)))
        return {"csrf": csrf}

    @app.get("/api/audit")
    def audit_entries(user=Depends(authenticate), limit: int = 300, offset: int = 0, action: str = ""):
        require_role(user, "admin")
        limit = max(1, min(limit, 1000))
        with connect(settings) as db:
            if action:
                rows = db.execute("SELECT * FROM audit WHERE action LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?",
                                  (action.replace("%", "") + "%", limit, max(0, offset)))
            else:
                rows = db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ? OFFSET ?", (limit, max(0, offset)))
            return [dict(r) for r in rows]

    @app.get("/{full_path:path}", response_class=HTMLResponse)
    def spa(full_path: str):
        # Client-side routes of the single page application; API paths stay 404.
        if full_path.startswith(SPA_PREFIXES):
            return (static / "index.html").read_text(encoding="utf8")
        raise HTTPException(404, "Not found")

    app.add_middleware(HttpTelemetryMiddleware, metrics=app.state.http_metrics)
    return app
