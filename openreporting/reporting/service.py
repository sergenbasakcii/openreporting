"""Report definitions, schedules, queued runs, artifact archive and e-mail delivery.

Fail-closed rules carried over from v0.4: a run that loses data sources, hits
query errors or NO DATA is ``partial`` and is not mailed unless the report owner
explicitly allows partial delivery; an interrupted SMTP exchange is never
retried automatically; downloads are verified against the audited manifest hash.
"""
import hashlib
import json
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .. import dashboards, folder_access
from ..db import audit, connect, transaction, utcnow
from ..domain import DomainError, canonical, identity, parse_utc, sha, validate_emails
from ..postgres_store import assert_worker_ownership
from ..mail_transport import connection as smtp_connection
from ..timerange import TimeRangeError, resolve_range
from ..worker import _atomic_write, completed_period, schedule_next
from . import logos
from .collect import collect
from .excel import render_csv, render_xlsx
from .pdf import render_pdf

log = logging.getLogger(__name__)
FORMATS = ("pdf", "xlsx", "csv")
CADENCES = ("hourly", "daily", "weekly", "monthly", "yearly")
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MIME = {"pdf": ("application", "pdf"), "xlsx": ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "csv": ("text", "csv"), "manifest": ("application", "json")}


class ReportError(DomainError):
    pass


class MailSetupError(Exception):
    """Connection failed before any message delivery command was attempted."""


def _actor_authorized(db,settings,actor_id,*,admin=False):
    row=db.execute('''SELECT u.active,u.role,e.provider FROM users u
        LEFT JOIN external_identities e ON e.user_id=u.id WHERE u.id=?''',(actor_id,)).fetchone()
    return bool(row and row['active'] and row['role'] in (('admin',) if admin else ('admin','editor'))
                and (row['provider']!='ldap' or settings.ldap_enabled))


def _run_authorized(db,settings,run):
    report = db.execute("SELECT dashboard_uid FROM dash_reports WHERE id=?", (run["report_id"],)).fetchone()
    actor_id = run["created_by"]
    if run["schedule_id"]:
        approval = db.execute("SELECT approved_by FROM dash_report_schedules WHERE id=?", (run["schedule_id"],)).fetchone()
        actor_id = approval["approved_by"] if approval else None
    if not actor_id or not report:
        return False
    dashboard = db.execute("SELECT folder_id FROM dashboards WHERE uid=?", (report["dashboard_uid"],)).fetchone()
    if not dashboard or not folder_access.allowed(db, {"id": actor_id}, dashboard["folder_id"], edit=True):
        return False
    if run['schedule_id']:
        schedule=db.execute('SELECT * FROM dash_report_schedules WHERE id=?',(run['schedule_id'],)).fetchone()
        if not schedule or not schedule['enabled'] or schedule['report_id']!=run['report_id']:
            return False
        dashboard=db.execute('''SELECT d.version FROM dashboards d JOIN dash_reports r ON r.dashboard_uid=d.uid
            WHERE r.id=?''',(run['report_id'],)).fetchone()
        return bool(dashboard and schedule['approved_config_sha256']==run['config_sha256']
                    and schedule['approved_dashboard_version']==dashboard['version']
                    and _actor_authorized(db,settings,schedule['approved_by'],admin=True))
    return _actor_authorized(db,settings,run['created_by'],admin=bool(json.loads(run['recipients_json'])))


def _block_authorization(db,run_id):
    db.execute("UPDATE dash_report_runs SET status='blocked',delivery_status='blocked_revalidation',error=?,finished_at=? WHERE id=?",
               ('Rapor çalıştırma veya zamanlama onay yetkisi artık geçerli değil',utcnow(),run_id))
    audit(db,'worker','report_run.blocked_authorization','dash_report_run',run_id)


def validate_config(body, settings, principal=None):
    if not isinstance(body, dict):
        raise ReportError("Rapor yapılandırması geçersiz")
    name = str(body.get("name", "")).strip()
    if not 2 <= len(name) <= 200 or any(ord(c) < 32 for c in name):
        raise ReportError("Rapor adı 2-200 karakter olmalı")
    uid = str(body.get("dashboard_uid", ""))
    dashboards.get(settings, uid, principal)
    time_range = body.get("time_range") or {"from": "now-24h", "to": "now"}
    tz = str(body.get("timezone") or "Europe/Istanbul")
    try:
        ZoneInfo(tz) if tz not in ("UTC", "utc") else None
        resolve_range(time_range.get("from"), time_range.get("to"), tz)
    except (TimeRangeError, ZoneInfoNotFoundError, ValueError) as exc:
        raise ReportError(f"Zaman aralığı/saat dilimi geçersiz: {exc}") from exc
    formats = [f for f in body.get("formats") or ["pdf"] if f in FORMATS]
    if not formats:
        raise ReportError("En az bir çıktı biçimi seçin (pdf, xlsx, csv)")
    variables = body.get("variables") or {}
    if not isinstance(variables, dict) or len(json.dumps(variables)) > 20000:
        raise ReportError("Değişken değerleri geçersiz")
    split = body.get("split_by") or None
    if split is not None and not str(split).replace("_", "").isalnum():
        raise ReportError("Bölümleme değişkeni geçersiz")
    panel_ids = body.get("panel_ids") or []
    if not isinstance(panel_ids, list) or not all(isinstance(i, int) for i in panel_ids):
        raise ReportError("Panel seçimi geçersiz")
    config = {
        "name": name, "description": str(body.get("description", ""))[:2000], "dashboard_uid": uid,
        "time_range": {"from": str(time_range["from"]), "to": str(time_range["to"])}, "timezone": tz,
        "variables": variables, "split_by": split, "panel_ids": panel_ids,
        "include_collapsed": bool(body.get("include_collapsed", True)),
        "layout": "simple" if body.get("layout") == "simple" else "grid",
        "orientation": "portrait" if body.get("orientation") == "portrait" else "landscape",
        "paper": body.get("paper") if body.get("paper") in ("A4", "A3", "Letter") else "A4",
        "formats": formats, "cover": bool(body.get("cover", True)), "toc": bool(body.get("toc", True)),
        "footer_text": str(body.get("footer_text", ""))[:200],
        "logo_id": _logo_id(settings, body.get("logo_id")),
        "logo_on_cover": bool(body.get("logo_on_cover", True)),
        "logo_on_pages": bool(body.get("logo_on_pages", True)),
        "table_max_rows": max(10, min(int(body.get("table_max_rows") or 500), 20000)),
        "send_partial": bool(body.get("send_partial", False)),
        "email_subject": str(body.get("email_subject", ""))[:300],
        "email_message": str(body.get("email_message", ""))[:4000],
    }
    return config


def _logo_id(settings, value):
    if not value:
        return None
    logos.path(settings, value)  # must be an uploaded, validated logo
    return value


def _row(row):
    data = dict(row)
    data["config"] = json.loads(data.pop("config_json"))
    return data


def list_reports(settings, user=None):
    with connect(settings) as db:
        visible, values = folder_access.visible_sql(db, user, "d.folder_id")
        rows = db.execute("""SELECT r.*, d.title AS dashboard_title,
               (SELECT COUNT(*) FROM dash_report_schedules s WHERE s.report_id=r.id AND s.enabled=1) AS active_schedules,
               (SELECT status FROM dash_report_runs x WHERE x.report_id=r.id ORDER BY x.created_at DESC LIMIT 1) AS last_status,
               (SELECT created_at FROM dash_report_runs x WHERE x.report_id=r.id ORDER BY x.created_at DESC LIMIT 1) AS last_run_at
               FROM dash_reports r JOIN dashboards d ON d.uid=r.dashboard_uid WHERE """ + visible + " ORDER BY LOWER(r.name),r.id", values).fetchall()
    return [_row(r) for r in rows]


def get_report(settings, report_id, user=None):
    with connect(settings) as db:
        row = folder_access.require_report(db, user, report_id)
    if not row:
        raise ReportError("Rapor bulunamadı")
    return _row(row)


def save_report(settings, user, body, report_id=None):
    config = validate_config(body, settings, user)
    now = utcnow()
    disabled = 0
    with connect(settings) as db, transaction(db):
        folder_access.require_dashboard(db, user, config["dashboard_uid"], edit=True)
        if report_id:
            row = folder_access.require_report(db, user, report_id, edit=True)
            if not row:
                raise ReportError("Rapor bulunamadı")
            if row["dashboard_uid"] != config["dashboard_uid"] and db.execute(
                    "SELECT 1 FROM dash_report_runs WHERE report_id=? LIMIT 1", (report_id,)).fetchone():
                raise ReportError("Arşivi olan raporun dashboard bağlantısı değiştirilemez; yeni rapor oluşturun")
            revision = row["revision"] + 1
            db.execute("""UPDATE dash_reports SET name=?,dashboard_uid=?,config_json=?,config_sha256=?,revision=?,updated_at=?,
                          updated_by=? WHERE id=?""", (config["name"], config["dashboard_uid"], canonical(config), sha(config),
                                                        revision, now, user["id"], report_id))
            disabled = db.execute("UPDATE dash_report_schedules SET enabled=0,updated_at=? WHERE report_id=? AND enabled=1",
                                  (now, report_id)).rowcount
            audit(db, user["id"], "report.updated", "dash_report", report_id,
                  {"revision": revision, "schedules_disabled": disabled})
        else:
            report_id = identity()
            revision = 1
            db.execute("INSERT INTO dash_reports VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (report_id, config["name"], config["dashboard_uid"], canonical(config), sha(config), 1, now, now,
                        user["id"], user["id"]))
            audit(db, user["id"], "report.created", "dash_report", report_id, {"dashboard": config["dashboard_uid"]})
    return {"id": report_id, "revision": revision, "schedules_disabled": disabled}


def delete_report(settings, user, report_id):
    with connect(settings) as db, transaction(db):
        folder_access.require_report(db, user, report_id, edit=True)
        if not db.execute("SELECT 1 FROM dash_reports WHERE id=?", (report_id,)).fetchone():
            raise ReportError("Rapor bulunamadı")
        files = [name for row in db.execute("SELECT files_json FROM dash_report_runs WHERE report_id=?", (report_id,))
                 for name in json.loads(row["files_json"]).values()]
        db.execute("DELETE FROM dash_report_runs WHERE report_id=?", (report_id,))
        db.execute("DELETE FROM dash_report_schedules WHERE report_id=?", (report_id,))
        db.execute("DELETE FROM dash_reports WHERE id=?", (report_id,))
        audit(db, user["id"], "report.deleted", "dash_report", report_id, {"archive_files": len(files)})
    for name in files:
        target = settings.archive_dir / name
        if target.parent == settings.archive_dir and target.is_file():
            target.unlink()


# --- schedules ----------------------------------------------------------------

def next_due(cadence, tz_name, hour, minute, weekday=0, month_day=1, reference=None):
    tz = ZoneInfo(tz_name) if tz_name not in ("UTC", "utc") else timezone.utc
    ref = (reference or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if cadence == "hourly":
        candidate = ref.replace(second=0, microsecond=0)
        for step in range(1, 62):
            probe = candidate + timedelta(minutes=step)
            if probe.astimezone(tz).minute == minute:
                return probe.isoformat(timespec="seconds")
        raise ReportError("Saatlik zamanlama hesaplanamadı")
    if cadence == "weekly":
        local = ref.astimezone(tz)
        for days in range(0, 8):
            day = (local + timedelta(days=days)).date()
            if day.weekday() != weekday:
                continue
            due = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
            if due > ref:
                return due.astimezone(timezone.utc).isoformat(timespec="seconds")
        raise ReportError("Haftalık zamanlama hesaplanamadı")
    if cadence == "monthly":
        local = ref.astimezone(tz)
        year, month = local.year, local.month
        for _ in range(14):
            due = datetime(year, month, min(month_day, 28), hour, minute, tzinfo=tz)
            if due > ref:
                return due.astimezone(timezone.utc).isoformat(timespec="seconds")
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        raise ReportError("Aylık zamanlama hesaplanamadı")
    if cadence in ("daily", "yearly"):
        return schedule_next(cadence, tz_name if tz_name not in ("UTC", "utc") else "UTC", hour, minute, ref)
    raise ReportError("Geçersiz periyot")


def schedule_period(cadence, tz_name, due_iso, range_mode, report_config):
    due = parse_utc(due_iso)
    if range_mode == "report":
        start, end = resolve_range(report_config["time_range"]["from"], report_config["time_range"]["to"],
                                   report_config["timezone"], now=due)
        return start.isoformat(), end.isoformat()
    if cadence == "hourly":
        end = due.replace(minute=0, second=0, microsecond=0)
        return (end - timedelta(hours=1)).isoformat(), end.isoformat()
    return completed_period(cadence, tz_name if tz_name not in ("UTC", "utc") else "UTC", due_iso)


def save_schedule(settings, user, report_id, body, schedule_id=None):
    cadence = body.get("cadence", "daily")
    if cadence not in CADENCES:
        raise ReportError("Geçersiz periyot")
    tz = str(body.get("timezone") or "Europe/Istanbul")
    try:
        if tz not in ("UTC", "utc"):
            ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise ReportError("Bilinmeyen saat dilimi") from exc
    hour, minute = int(body.get("hour", 8)), int(body.get("minute", 0))
    weekday, month_day = int(body.get("weekday", 0)), int(body.get("month_day", 1))
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= weekday <= 6 and 1 <= month_day <= 28):
        raise ReportError("Saat, dakika, gün değerleri geçersiz")
    range_mode = "report" if body.get("range_mode") == "report" else "previous_period"
    recipients = validate_emails(body.get("recipients") or [], settings.recipient_domains) if body.get("recipients") else []
    enabled = bool(body.get("enabled"))
    if enabled and user["role"] != "admin":
        raise ReportError("Zamanlamayı yalnızca yönetici etkinleştirebilir")
    if enabled and recipients and not settings.mail_enabled:
        raise ReportError("E-posta kapalı (OPENREPORTING_MAIL_ENABLED); alıcısız arşiv zamanlaması kullanın veya SMTP’yi etkinleştirin")
    due = next_due(cadence, tz, hour, minute, weekday, month_day)
    now = utcnow()
    with connect(settings) as db, transaction(db):
        report = folder_access.require_report(db, user, report_id, edit=True)
        if not report:
            raise ReportError("Rapor bulunamadı")
        if not _actor_authorized(db,settings,user['id'],admin=enabled):
            raise ReportError('Rapor zamanlama yetkisi artık geçerli değil')
        dash = db.execute("SELECT version FROM dashboards WHERE uid=?", (report["dashboard_uid"],)).fetchone()
        approval = (report["config_sha256"], dash["version"] if dash else None, user["id"]) if enabled else (None, None, None)
        if schedule_id:
            if not db.execute("SELECT 1 FROM dash_report_schedules WHERE id=? AND report_id=?", (schedule_id, report_id)).fetchone():
                raise ReportError("Zamanlama bulunamadı")
            db.execute("""UPDATE dash_report_schedules SET cadence=?,timezone=?,hour=?,minute=?,weekday=?,month_day=?,range_mode=?,
                          recipients_json=?,enabled=?,next_due=?,updated_at=?,approved_config_sha256=?,
                          approved_dashboard_version=?,approved_by=? WHERE id=?""",
                       (cadence, tz, hour, minute, weekday, month_day, range_mode, canonical(recipients), int(enabled), due, now,
                        *approval, schedule_id))
            action = "report_schedule.updated"
        else:
            schedule_id = identity()
            db.execute("""INSERT INTO dash_report_schedules(id,report_id,cadence,timezone,hour,minute,weekday,month_day,range_mode,
                          recipients_json,enabled,next_due,created_by,updated_at,approved_config_sha256,
                          approved_dashboard_version,approved_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (schedule_id, report_id, cadence, tz, hour, minute, weekday, month_day, range_mode, canonical(recipients),
                        int(enabled), due, user["id"], now, *approval))
            action = "report_schedule.created"
        audit(db, user["id"], action, "dash_report_schedule", schedule_id, {"enabled": enabled, "cadence": cadence,
                                                                           "recipients": len(recipients)})
    return {"id": schedule_id, "next_due": due, "enabled": enabled}


def list_schedules(settings, report_id=None, user=None):
    sql = """SELECT s.*, r.name AS report_name FROM dash_report_schedules s JOIN dash_reports r ON r.id=s.report_id JOIN dashboards d ON d.uid=r.dashboard_uid WHERE 1=1"""
    params = []
    if report_id:
        sql += " AND s.report_id=?"
        params = [report_id]
    with connect(settings) as db:
        if report_id:
            folder_access.require_report(db, user, report_id)
        visible, values = folder_access.visible_sql(db, user, "d.folder_id")
        rows = db.execute(sql + " AND " + visible + " ORDER BY s.next_due", [*params, *values]).fetchall()
    return [{**dict(r), "recipients": json.loads(r["recipients_json"])} for r in rows]


def delete_schedule(settings, user, schedule_id):
    with connect(settings) as db, transaction(db):
        schedule = db.execute("SELECT report_id FROM dash_report_schedules WHERE id=?", (schedule_id,)).fetchone()
        if schedule:
            folder_access.require_report(db, user, schedule["report_id"], edit=True)
        if not db.execute("DELETE FROM dash_report_schedules WHERE id=?", (schedule_id,)).rowcount:
            raise ReportError("Zamanlama bulunamadı")
        audit(db, user["id"], "report_schedule.deleted", "dash_report_schedule", schedule_id)


# --- runs -------------------------------------------------------------------------

def enqueue(db, report, actor, start, end, schedule_id=None, recipients=()):
    run_id = identity()
    key = sha([report["id"], report["revision"], schedule_id or f"manual:{run_id}", start, end])
    inserted = db.execute("""INSERT INTO dash_report_runs(id,report_id,schedule_id,revision,config_sha256,period_start,period_end,
                      idempotency_key,status,recipients_json,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,'queued',?,?,?)
                      ON CONFLICT(idempotency_key) DO NOTHING""",
                          (run_id, report["id"], schedule_id, report["revision"], report["config_sha256"], start, end, key,
                           canonical(list(recipients)), actor, utcnow()))
    if not inserted.rowcount:
        existing = db.execute("SELECT id FROM dash_report_runs WHERE idempotency_key=?", (key,)).fetchone()
        if not existing:
            raise ReportError("Rapor kuyruğundaki mevcut çalışma bulunamadı")
        return existing["id"]
    audit(db, actor or "scheduler", "report_run.queued", "dash_report_run", run_id, {"report_id": report["id"]})
    return run_id


def request_run(settings, user, report_id, body):
    report = get_report(settings, report_id, user)
    config = report["config"]
    rng = body.get("time_range") or config["time_range"]
    try:
        start, end = resolve_range(rng.get("from"), rng.get("to"), config["timezone"])
    except TimeRangeError as exc:
        raise ReportError(str(exc)) from exc
    recipients = []
    if body.get("recipients"):
        if not settings.mail_enabled:
            raise ReportError("E-posta gönderimi kapalı (OPENREPORTING_MAIL_ENABLED=false)")
        if user["role"] != "admin":
            raise ReportError("Anlık e-posta gönderimi yalnızca yöneticiye açıktır")
        recipients = validate_emails(body["recipients"], settings.recipient_domains)
    with connect(settings) as db, transaction(db):
        row = folder_access.require_report(db, user, report_id, edit=True)
        if not _actor_authorized(db,settings,user['id'],admin=bool(recipients)):
            raise ReportError('Rapor çalıştırma yetkisi artık geçerli değil')
        run_id = enqueue(db, row, user["id"], start.isoformat(), end.isoformat(), None, recipients)
    return {"run_id": run_id, "status": "queued"}


def list_runs(settings, report_id=None, limit=200, user=None):
    sql = """SELECT x.*, r.name AS report_name FROM dash_report_runs x JOIN dash_reports r ON r.id=x.report_id JOIN dashboards d ON d.uid=r.dashboard_uid WHERE 1=1"""
    params = []
    if report_id:
        sql += " AND x.report_id=?"
        params.append(report_id)
    with connect(settings) as db:
        if report_id:
            folder_access.require_report(db, user, report_id)
        visible, values = folder_access.visible_sql(db, user, "d.folder_id")
        sql += " AND " + visible + " ORDER BY x.created_at DESC LIMIT ?"
        rows = db.execute(sql, [*params, *values, max(1, min(int(limit), 1000))]).fetchall()
    return [{**dict(r), "files": json.loads(r["files_json"]), "warnings": json.loads(r["warnings_json"]),
             "recipients": json.loads(r["recipients_json"])} for r in rows]


def tick_schedules(settings):
    now = datetime.now(timezone.utc)
    with connect(settings) as db:
        due_ids = [r["id"] for r in db.execute(
            "SELECT id FROM dash_report_schedules WHERE enabled=1 AND next_due<=? ORDER BY next_due LIMIT 100",
            (now.isoformat(),))]
    for schedule_id in due_ids:
        try:
            _tick_one(settings, schedule_id, now)
        except Exception as exc:  # noqa: BLE001 - isolate one bad schedule from the rest
            log.exception("Schedule %s failed", schedule_id)
            with connect(settings) as db, transaction(db):
                db.execute("UPDATE dash_report_schedules SET enabled=0,updated_at=? WHERE id=?", (utcnow(), schedule_id))
                audit(db, "scheduler", "report_schedule.failed_disabled", "dash_report_schedule", schedule_id,
                      {"error": str(exc)[:300]})


def _tick_one(settings, schedule_id, now):
    with connect(settings) as db, transaction(db):
        sched = db.execute("SELECT * FROM dash_report_schedules WHERE id=? AND enabled=1", (schedule_id,)).fetchone()
        if sched is None or sched["next_due"] > now.isoformat():
            return
        following = next_due(sched["cadence"], sched["timezone"], sched["hour"], sched["minute"], sched["weekday"],
                             sched["month_day"], now)
        db.execute("UPDATE dash_report_schedules SET next_due=?,updated_at=? WHERE id=?", (following, utcnow(), sched["id"]))
        if now - parse_utc(sched["next_due"]) > timedelta(hours=2):
            # No catch-up storms after downtime: record and move on.
            audit(db, "scheduler", "report_schedule.missed_window", "dash_report_schedule", sched["id"])
            return
        report = db.execute("SELECT * FROM dash_reports WHERE id=?", (sched["report_id"],)).fetchone()
        if report is None:
            return
        if not _actor_authorized(db,settings,sched['approved_by'],admin=True):
            db.execute('UPDATE dash_report_schedules SET enabled=0,updated_at=? WHERE id=?',(utcnow(),sched['id']))
            audit(db,'scheduler','report_schedule.disabled_authorization','dash_report_schedule',sched['id'])
            return
        dash = db.execute("SELECT version FROM dashboards WHERE uid=?", (report["dashboard_uid"],)).fetchone()
        if (sched["approved_config_sha256"] != report["config_sha256"]
                or sched["approved_dashboard_version"] != (dash["version"] if dash else None)):
            # The report or its dashboard changed after the admin approved this schedule.
            db.execute("UPDATE dash_report_schedules SET enabled=0,updated_at=? WHERE id=?", (utcnow(), sched["id"]))
            audit(db, "scheduler", "report_schedule.disabled_changed", "dash_report_schedule", sched["id"],
                  {"report_revision": report["revision"], "dashboard_version": dash["version"] if dash else None})
            return
        config = json.loads(report["config_json"])
        start, end = schedule_period(sched["cadence"], sched["timezone"], sched["next_due"], sched["range_mode"], config)
        run_id = enqueue(db, report, None, start, end, sched["id"], json.loads(sched["recipients_json"]))
        db.execute("UPDATE dash_report_schedules SET last_run_id=? WHERE id=?", (run_id, sched["id"]))


def claim(settings):
    with connect(settings) as db, transaction(db):
        row = db.execute("SELECT id FROM dash_report_runs WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
        if not row:
            return None
        lease = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(timespec="seconds")
        db.execute("UPDATE dash_report_runs SET status='running',owner=?,lease_until=?,started_at=? WHERE id=?",
                   (identity(), lease, utcnow(), row["id"]))
        return row["id"]


def mark_interrupted(settings, force=False):
    with connect(settings) as db, transaction(db):
        rows = db.execute("SELECT id FROM dash_report_runs WHERE (status='running' OR delivery_status='sending')" + ("" if force else " AND lease_until<?"),
                          () if force else (utcnow(),)).fetchall()
        for row in rows:
            # Unfinished renders need review. A finished run (completed/partial) whose e-mail was in
            # flight keeps its status and files; only the delivery becomes 'unknown' (never resent).
            db.execute("""UPDATE dash_report_runs SET
                          status=CASE WHEN status='running' THEN 'needs_review' ELSE status END,
                          delivery_status=CASE WHEN delivery_status='sending' THEN 'unknown' ELSE delivery_status END,
                          error=CASE WHEN status='running' THEN 'Çalıştırma yarıda kaldı; manuel inceleme gerekli'
                                     ELSE 'E-posta gönderimi yarıda kaldı; teslim durumu bilinmiyor' END
                          WHERE id=?""", (row["id"],))
            audit(db, "worker", "report_run.interrupted", "dash_report_run", row["id"])


def report_logo(settings, config):
    """PNG bytes of the report's customer logo, or None."""
    if not config.get("logo_id"):
        return None
    try:
        return logos.path(settings, config["logo_id"]).read_bytes()
    except logos.LogoError:
        # A missing logo is cosmetic: the report is still complete and may be delivered.
        log.warning("Report %s: logo %s unavailable, rendering without it", config.get("name"), config["logo_id"])
        return None


def build_outputs(settings, config, title, start, end, *, user="report", formats=None, trusted=True, principal=None):
    dashboard = dashboards.get(settings, config["dashboard_uid"], principal)["dashboard"]
    collected = collect(settings, dashboard, config, start, end, user=user, trusted=trusted)
    outputs = {}
    logo = report_logo(settings, config)
    for fmt in formats or config["formats"]:
        if fmt == "pdf":
            outputs["pdf"] = render_pdf(config, collected, title, logo=logo)
        elif fmt == "xlsx":
            outputs["xlsx"] = render_xlsx(config, collected, title)
        elif fmt == "csv":
            outputs["csv"] = render_csv(config, collected, title)
    with connect(settings) as db:
        folder_access.require_dashboard(db, principal, config["dashboard_uid"])
    return collected, outputs, dashboard


def execute(settings, run_id):
    with connect(settings) as db:
        run = db.execute("SELECT * FROM dash_report_runs WHERE id=?", (run_id,)).fetchone()
        report = db.execute("SELECT * FROM dash_reports WHERE id=?", (run["report_id"],)).fetchone() if run else None
        if run is not None and not _run_authorized(db,settings,run):
            with transaction(db):
                _block_authorization(db,run_id)
            return
    if run is None:
        return
    with connect(settings) as db:
        actor_id = run["created_by"]
        if run["schedule_id"]:
            schedule = db.execute("SELECT approved_by FROM dash_report_schedules WHERE id=?", (run["schedule_id"],)).fetchone()
            actor_id = schedule["approved_by"] if schedule else None
        actor = folder_access.principal(db, {"id": actor_id})
    if report is None or report["config_sha256"] != run["config_sha256"]:
        with connect(settings) as db, transaction(db):
            db.execute("UPDATE dash_report_runs SET status='blocked',error=?,finished_at=? WHERE id=?",
                       ("Rapor kuyruğa alındıktan sonra değişti veya silindi", utcnow(), run_id))
            audit(db, "worker", "report_run.blocked", "dash_report_run", run_id)
        return
    config = json.loads(report["config_json"])
    try:
        collected, outputs, dashboard = build_outputs(settings, config, config["name"], parse_utc(run["period_start"]),
                                                      parse_utc(run["period_end"]), principal=actor)
        with connect(settings) as db,transaction(db):
            if not _run_authorized(db,settings,run):
                _block_authorization(db,run_id)
                return
        stamp = parse_utc(run["period_start"]).strftime("%Y%m%d-%H%M")
        safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in config["name"])[:60] or "rapor"
        files = {}
        digests = {}
        for fmt, payload in outputs.items():
            assert_worker_ownership()
            filename = f"rapor-{run_id[:8]}-{safe_name}-{stamp}.{fmt}"
            _atomic_write(settings.archive_dir / filename, payload)
            files[fmt] = filename
            digests[fmt] = hashlib.sha256(payload).hexdigest()
        warnings = list(collected.warnings) + [f"{p.title or p.panel.get('type')}: {msg}" for s in collected.sections
                                                for p in s.panels for msg in (p.errors + p.warnings)]
        manifest = {"schema_version": 2, "run_id": run_id, "report_id": report["id"], "report_revision": run["revision"],
                    "config_sha256": run["config_sha256"], "dashboard_uid": dashboard["uid"],
                    "dashboard_version": dashboard.get("version"), "period_start": run["period_start"],
                    "period_end": run["period_end"], "timezone": config["timezone"], "partial": collected.partial,
                    "sections": [s.title for s in collected.sections], "warnings": warnings[:500],
                    "variables": {k: v.get("value") for k, v in collected.variables.items()},
                    "sha256": digests, "created_at": utcnow()}
        manifest_bytes = canonical(manifest).encode()
        files["manifest"] = f"rapor-{run_id[:8]}-{safe_name}-{stamp}.json"
        _atomic_write(settings.archive_dir / files["manifest"], manifest_bytes)
    except Exception as exc:  # noqa: BLE001 - recorded on the run
        log.exception("Report run %s failed", run_id)
        with connect(settings) as db, transaction(db):
            if not _run_authorized(db, settings, run):
                _block_authorization(db, run_id)
                return
            db.execute("UPDATE dash_report_runs SET status='failed',error=?,finished_at=? WHERE id=?",
                       (str(exc)[:500], utcnow(), run_id))
            audit(db, "worker", "report_run.failed", "dash_report_run", run_id)
        return
    recipients = json.loads(run["recipients_json"])
    partial = collected.partial
    deliver = bool(recipients) and settings.mail_enabled and (not partial or config.get("send_partial"))
    delivery = ("pending" if deliver else "blocked_partial" if recipients and partial else
                "disabled" if recipients and not settings.mail_enabled else "not_requested")
    with connect(settings) as db, transaction(db):
        db.execute("""UPDATE dash_report_runs SET status=?,finished_at=?,files_json=?,warnings_json=?,delivery_status=? WHERE id=?""",
                   ("partial" if partial else "completed", utcnow(), canonical(files), canonical(warnings[:200]), delivery, run_id))
        audit(db, "worker", "report_run.partial" if partial else "report_run.completed", "dash_report_run", run_id,
              {"manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()})
    if not deliver:
        return
    with connect(settings) as db, transaction(db):
        current = db.execute("SELECT config_sha256 FROM dash_reports WHERE id=?", (report["id"],)).fetchone()
        schedule = db.execute("SELECT enabled FROM dash_report_schedules WHERE id=?", (run["schedule_id"],)).fetchone() \
            if run["schedule_id"] else None
        if not current or current["config_sha256"] != run["config_sha256"] or (run["schedule_id"] and (not schedule or not schedule["enabled"])) or not _run_authorized(db,settings,run):
            db.execute("UPDATE dash_report_runs SET delivery_status='blocked_revalidation' WHERE id=?", (run_id,))
            audit(db, "worker", "report_delivery.blocked", "dash_report_run", run_id)
            return
        size = sum((settings.archive_dir / files[f]).stat().st_size for f in config["formats"] if files.get(f))
        if size > MAX_ATTACHMENT_BYTES:
            db.execute("UPDATE dash_report_runs SET delivery_status='blocked_too_large' WHERE id=?", (run_id,))
            audit(db, "worker", "report_delivery.blocked_too_large", "dash_report_run", run_id, {"bytes": size})
            return
        db.execute("UPDATE dash_report_runs SET delivery_status='sending' WHERE id=?", (run_id,))
        audit(db, "worker", "report_delivery.attempted", "dash_report_run", run_id)
    try:
        status = send_mail(settings, config, run, files, recipients, partial)
    except (MailSetupError, smtplib.SMTPRecipientsRefused, smtplib.SMTPAuthenticationError, smtplib.SMTPSenderRefused,
            smtplib.SMTPDataError, smtplib.SMTPNotSupportedError):
        log.warning("Report mail delivery rejected for %s", run_id)
        status = "failed"
    except Exception:  # noqa: BLE001 - SMTP may have accepted the message; never retry automatically
        log.warning("Report mail delivery uncertain for %s", run_id)
        status = "unknown"
    with connect(settings) as db, transaction(db):
        db.execute("UPDATE dash_report_runs SET delivery_status=? WHERE id=?", (status, run_id))
        audit(db, "worker", f"report_delivery.{status}", "dash_report_run", run_id)


def send_mail(settings, config, run, files, recipients, partial):
    if not settings.mail_enabled:
        return "disabled"
    recipients = validate_emails(recipients, settings.recipient_domains)
    tz = ZoneInfo(config["timezone"]) if config["timezone"] not in ("UTC", "utc") else timezone.utc
    start = parse_utc(run["period_start"]).astimezone(tz).strftime("%d.%m.%Y %H:%M")
    end = parse_utc(run["period_end"]).astimezone(tz).strftime("%d.%m.%Y %H:%M")
    subject = (config.get("email_subject") or "{report} | {from} – {to}").replace("{report}", config["name"]) \
        .replace("{from}", start).replace("{to}", end)
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = ", ".join(recipients)
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(idstring=run["id"], domain=settings.smtp_from.rsplit("@", 1)[-1])
    message["Subject"] = subject.replace("\r", " ").replace("\n", " ")[:250]
    body = config.get("email_message") or "Rapor ektedir."
    if partial:
        body += "\n\nUYARI: Bu raporda bazı paneller hata veya eksik veri içeriyor (kısmi rapor)."
    if settings.public_url:
        body += f"\n\nArşiv: {settings.public_url}/reports/{run['report_id']}"
    message.set_content(body)
    total = 0
    for fmt in config["formats"]:
        filename = files.get(fmt)
        if not filename:
            continue
        payload = (settings.archive_dir / filename).read_bytes()
        total += len(payload)
        if total > MAX_ATTACHMENT_BYTES:
            raise ReportError("Ekler 20 MB sınırını aşıyor")
        maintype, subtype = MIME[fmt]
        message.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)
    ready = False
    try:
        with smtp_connection(settings) as smtp:
            ready = True
            assert_worker_ownership()
            refused = smtp.send_message(message, from_addr=settings.smtp_from, to_addrs=recipients)
    except Exception:
        if not ready:
            raise MailSetupError("SMTP connection or authentication failed before delivery") from None
        raise
    return "partial_rejected" if refused else "sent"


def verified_file(settings, run_id, kind, user=None):
    """Return (path, filename) only when the manifest hash matches its audit anchor."""
    from ..db import verify_audit
    with connect(settings) as db:
        run = db.execute("SELECT * FROM dash_report_runs WHERE id=? AND status IN ('completed','partial')", (run_id,)).fetchone()
        if run:
            folder_access.require_report(db, user, run["report_id"])
        anchor = db.execute("""SELECT details FROM audit WHERE object_type='dash_report_run' AND object_id=? AND
                               action IN ('report_run.completed','report_run.partial') ORDER BY id DESC LIMIT 1""",
                            (run_id,)).fetchone()
        chain_ok, _ = verify_audit(db)
    if not run:
        raise ReportError("Çalıştırma bulunamadı")
    files = json.loads(run["files_json"])
    filename = files.get(kind)
    if not filename or "/" in filename or "\\" in filename or not files.get("manifest"):
        raise ReportError("Dosya bulunamadı")
    path = settings.archive_dir / filename
    manifest_path = settings.archive_dir / files["manifest"]
    if not chain_ok or not anchor or not path.is_file() or not manifest_path.is_file():
        raise ReportError("Arşiv bütünlüğü doğrulanamadı")
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != json.loads(anchor["details"]).get("manifest_sha256"):
        raise ReportError("Manifest özeti denetim kaydıyla uyuşmuyor")
    if kind != "manifest":
        manifest = json.loads(manifest_bytes)
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"].get(kind):
            raise ReportError("Dosya özeti manifestle uyuşmuyor")
    return path, filename


def apply_retention(settings):
    days = settings.report_retention_days
    if not days:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    removed = 0
    with connect(settings) as db, transaction(db):
        rows = db.execute("""SELECT id,files_json FROM dash_report_runs WHERE created_at<? AND
                             status IN ('completed','partial','failed','blocked') LIMIT 500""", (cutoff,)).fetchall()
        for row in rows:
            for filename in json.loads(row["files_json"]).values():
                target = settings.archive_dir / filename
                if target.is_file() and target.parent == settings.archive_dir:
                    target.unlink()
            db.execute("DELETE FROM dash_report_runs WHERE id=?", (row["id"],))
            removed += 1
        if removed:
            audit(db, "worker", "report_run.retention_cleanup", "dash_report_run", "batch", {"removed": removed, "days": days})
    return removed
