"""Boot data for the SPA, health and Prometheus-style metrics."""
import os
import platform
from datetime import datetime, timezone
from shutil import disk_usage

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .. import __version__
from ..db import audit, connect, transaction, verify_audit
from ..domain import parse_utc
from ..healthchecks import database_ready
from ..security import authenticate
from .deps import admin, admin_read, settings_of

router = APIRouter()


@router.get("/api/frontend/settings")
def frontend_settings(request: Request, user=Depends(authenticate)):
    settings = settings_of(request)
    return {"version": __version__, "mailEnabled": settings.mail_enabled,
            "recipientDomains": list(settings.recipient_domains), "publicUrl": settings.public_url,
            "platform": platform.system(), "features": {"reports": True, "explore": True}}


@router.get("/api/time/resolve")
def resolve_time(request: Request, start: str = "now-6h", end: str = "now", tz: str = "UTC", now: int | None = None,
                 user=Depends(authenticate)):
    """Resolve Grafana time expressions (``now/d``) in a time zone to epoch ms."""
    from ..timerange import TimeRangeError, resolve_range
    anchor = datetime.fromtimestamp(now / 1000, timezone.utc) if now else None
    try:
        frm, to = resolve_range(start, end, tz, now=anchor)
    except TimeRangeError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"from": int(frm.timestamp() * 1000), "to": int(to.timestamp() * 1000)}


@router.get("/api/health")
def health(request: Request):
    settings = settings_of(request)
    try:
        with connect(settings) as db:
            database = "ok" if database_ready(db) else "failing"
    except Exception:  # noqa: BLE001 - health must never raise
        database = "failing"
    return JSONResponse({"database": database, "version": __version__}, status_code=200 if database == "ok" else 503)


def _worker_state(settings):
    with connect(settings) as db:
        worker = db.execute("SELECT * FROM worker_runtime WHERE singleton_id=1").fetchone()
    if not worker:
        return None, None
    age = (datetime.now(timezone.utc) - parse_utc(worker["last_tick"])).total_seconds()
    return dict(worker), age


@router.get("/api/admin/stats")
def admin_stats(request: Request, user=Depends(admin_read)):
    settings = settings_of(request)
    with connect(settings) as db:
        counts = {name: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for name, table in (
            ("users", "users"), ("dashboards", "dashboards"), ("folders", "folders"), ("datasources", "datasources"),
            ("reports", "dash_reports"), ("schedules", "dash_report_schedules"), ("runs", "dash_report_runs"))}
        active_schedules = db.execute("SELECT COUNT(*) FROM dash_report_schedules WHERE enabled=1").fetchone()[0]
        run_status = [dict(r) for r in db.execute(
            "SELECT status,COUNT(*) AS count FROM dash_report_runs GROUP BY status")]
        audit_ok, broken = verify_audit(db)
    worker, age = _worker_state(settings)
    disk = disk_usage(settings.data_dir)
    archive_bytes = sum(f.stat().st_size for f in settings.archive_dir.glob("*") if f.is_file())
    return {"counts": counts, "activeSchedules": active_schedules, "runStatus": run_status,
            "auditChainValid": audit_ok, "auditBrokenId": broken,
            "worker": {**(worker or {}), "heartbeat_age_seconds": round(age, 1) if age is not None else None,
                       "state": "not_started" if worker is None else "up" if age < 120 else "stale"},
            "disk": {"free_bytes": disk.free, "total_bytes": disk.total, "archive_bytes": archive_bytes},
            "mailEnabled": settings.mail_enabled, "version": __version__, "python": platform.python_version(),
            "platform": f"{platform.system()} {platform.release()}", "pid": os.getpid()}


@router.get("/api/admin/integrations")
def integrations(request: Request, user=Depends(admin_read)):
    from ..mail_transport import security_mode
    settings = settings_of(request)
    return {"ldap": {"enabled": settings.ldap_enabled, "session_minutes": settings.ldap_session_minutes},
            "smtp": {"enabled": settings.mail_enabled, "security": security_mode(settings)}}


@router.post("/api/admin/integrations/{kind}/check")
def check_integration(kind: str, request: Request, user=Depends(admin)):
    from .. import directory_auth, mail_transport
    if kind not in {"ldap", "smtp"}:
        raise HTTPException(404, "Bağlantı bulunamadı")
    settings = settings_of(request)
    enabled = settings.ldap_enabled if kind == "ldap" else settings.mail_enabled
    if not enabled:
        raise HTTPException(409, "Bu bağlantı sunucu ayarlarında kapalı")
    try:
        check = directory_auth.check_connection if kind == "ldap" else mail_transport.check_connection
        message = check(settings)
        ok = True
    except Exception:  # Never expose directory responses, authentication challenges or secrets.
        ok = False
        message = "Bağlantı doğrulanamadı. DNS, port, sertifika ve hesap ayarlarını kontrol edin."
    with connect(settings) as db, transaction(db):
        audit(db, user["id"], "integration.checked", "integration", kind, {"ok": ok})
    return {"ok": ok, "message": message}


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(request: Request):
    """Prometheus exposition; loopback-only (scrape locally or through an authenticated proxy)."""
    client = request.client.host if request.client else ""
    if client not in ("127.0.0.1", "::1"):
        raise HTTPException(404, "Not found")
    settings = settings_of(request)
    lines = ["# HELP openreporting_up Application is serving requests", "# TYPE openreporting_up gauge", "openreporting_up 1"]
    with connect(settings) as db:
        for status, count in db.execute("SELECT status,COUNT(*) FROM dash_report_runs GROUP BY status"):
            lines.append(f'openreporting_report_runs_total{{status="{status}"}} {count}')
        for name, table in (("dashboards", "dashboards"), ("datasources", "datasources"), ("users", "users"),
                            ("reports", "dash_reports")):
            lines.append(f"openreporting_{name} {db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]}")
        enabled = db.execute("SELECT COUNT(*) FROM dash_report_schedules WHERE enabled=1").fetchone()[0]
        lines.append(f"openreporting_active_schedules {enabled}")
    worker, age = _worker_state(settings)
    if age is not None:
        lines.append(f"openreporting_worker_heartbeat_age_seconds {age:.1f}")
    disk = disk_usage(settings.data_dir)
    lines.append(f"openreporting_data_disk_free_bytes {disk.free}")
    return "\n".join(lines) + "\n"
