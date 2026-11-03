"""Report pipeline notifications (transactional outbox).

``notify`` records an event in the same transaction as the state change that caused it, so an
event is never lost and a rolled-back change never notifies. The worker delivers pending events
by e-mail (``deliver_pending``). Recipients are resolved at delivery time: the report's owner and
the schedule's creator and approving admin — only active accounts with an e-mail address in an
allowed domain, who have not opted out and can still open the report. Mails carry the report
name and a link, never report data. Delivery is at-least-once with a small retry budget.
"""

import logging
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from fastapi import HTTPException

from .. import folder_access
from ..db import connect, transaction, utcnow
from ..domain import DomainError, validate_emails
from ..mail_transport import connection as smtp_connection

log = logging.getLogger(__name__)

EVENTS = {
    "schedule_disabled_changed": "Zamanlama kapatıldı: rapor veya dashboard onaydan sonra değişti; yeniden onay gerekiyor",
    "schedule_disabled_authorization": "Zamanlama kapatıldı: onaylayan yöneticinin yetkisi kalmadı",
    "schedule_failed_disabled": "Zamanlama bir hata nedeniyle kapatıldı",
    "schedule_missed_window": "Zamanlanmış çalışma servis kesintisi nedeniyle atlandı",
    "schedules_disabled_report_changed": "Rapor değiştirildiği için zamanlamaları kapatıldı; yeniden onay gerekiyor",
    "run_failed": "Rapor çalışması başarısız oldu",
    "run_blocked": "Rapor çalışması yetki kontrolü nedeniyle durduruldu",
    "delivery_failed": "Rapor e-postası gönderilemedi",
    "delivery_unknown": "Rapor e-postasının teslim durumu belirsiz; posta sunucusu kayıtlarını kontrol edin",
}
BATCH = 50
MAX_ATTEMPTS = 3
KEEP_DAYS = 90


def notify(db, event, report_id, *, schedule_id=None, run_id=None, detail=""):
    """Queue an event inside the caller's transaction."""
    if event not in EVENTS:
        raise ValueError(f"Unknown notification event: {event}")
    db.execute(
        "INSERT INTO notification_outbox(event,report_id,schedule_id,run_id,detail,created_at) VALUES(?,?,?,?,?,?)",
        (event, report_id, schedule_id, run_id, str(detail or "")[:300], utcnow()),
    )


def _can_view(db, user, report_id):
    try:
        folder_access.require_report(db, user, report_id)
    except HTTPException:
        return False
    return True


def recipients(db, settings, item):
    """E-mail addresses that may receive this event (resolved now, not when it was queued)."""
    report = db.execute("SELECT created_by FROM dash_reports WHERE id=?", (item["report_id"],)).fetchone()
    if not report:
        return []
    ids = {report["created_by"]}
    if item["schedule_id"]:
        schedule = db.execute("SELECT created_by,approved_by FROM dash_report_schedules WHERE id=?", (item["schedule_id"],)).fetchone()
        if schedule:
            ids.update(x for x in (schedule["created_by"], schedule["approved_by"]) if x)
    found = []
    for user_id in sorted(i for i in ids if i):
        row = db.execute(
            """SELECT u.id,u.role,u.active,u.email,COALESCE(p.notify_report_failures,1) AS opted_in
               FROM users u LEFT JOIN user_prefs p ON p.user_id=u.id WHERE u.id=?""",
            (user_id,),
        ).fetchone()
        if not row or not row["active"] or not row["opted_in"] or not row["email"]:
            continue
        if not _can_view(db, {"id": row["id"], "role": row["role"]}, item["report_id"]):
            continue
        try:
            found.extend(validate_emails([row["email"]], settings.recipient_domains))
        except DomainError:
            continue  # outside the allowed recipient domains
    return sorted(set(found))


def _message(settings, item, report_name, to):
    title = EVENTS[item["event"]]
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(idstring=f"notify-{item['id']}", domain=settings.smtp_from.rsplit("@", 1)[-1])
    message["Subject"] = f"[OpenReporting] {report_name}: {title}".replace("\r", " ").replace("\n", " ")[:250]
    body = [f"Rapor: {report_name}", f"Olay: {title}", f"Zaman (UTC): {item['created_at']}"]
    if item["detail"]:
        body.append(f"Ayrıntı: {item['detail']}")
    if settings.public_url:
        body.append(f"Rapor: {settings.public_url}/reports/{item['report_id']}")
    body.append("\nBu bildirimi Profil > Tercihler bölümünden kapatabilirsiniz.")
    message.set_content("\n".join(body))
    return message


def _finish(settings, item_id, status, attempts):
    with connect(settings) as db, transaction(db):
        db.execute(
            "UPDATE notification_outbox SET status=?,attempts=?,sent_at=? WHERE id=? AND status='pending'",
            (status, attempts, utcnow() if status == "sent" else None, item_id),
        )


def deliver_pending(settings):
    """Worker phase: send pending notifications. Returns the number of items processed."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    with connect(settings) as db, transaction(db):
        db.execute("DELETE FROM notification_outbox WHERE status<>'pending' AND created_at<?", (cutoff,))
        pending = [dict(r) for r in db.execute("SELECT * FROM notification_outbox WHERE status='pending' ORDER BY id LIMIT ?", (BATCH,))]
        if not settings.mail_enabled:
            # Nobody can be e-mailed; events stay visible in the application (Reports page).
            db.execute("UPDATE notification_outbox SET status='skipped' WHERE status='pending'")
            return len(pending)
        work = []
        for item in pending:
            report = db.execute("SELECT name FROM dash_reports WHERE id=?", (item["report_id"],)).fetchone()
            work.append((item, report["name"] if report else item["report_id"], recipients(db, settings, item)))
    for item, report_name, addresses in work:
        if not addresses:
            _finish(settings, item["id"], "skipped", item["attempts"])
            continue
        try:
            with smtp_connection(settings) as smtp:
                for address in addresses:
                    smtp.send_message(_message(settings, item, report_name, address), from_addr=settings.smtp_from, to_addrs=[address])
        except Exception:  # noqa: BLE001 - retried a few times, never in a tight loop
            attempts = item["attempts"] + 1
            log.warning("Notification %s delivery failed (attempt %s)", item["id"], attempts)
            _finish(settings, item["id"], "failed" if attempts >= MAX_ATTEMPTS else "pending", attempts)
            continue
        _finish(settings, item["id"], "sent", item["attempts"] + 1)
    return len(work)


def recent_for(settings, user, limit=50):
    """Recent events for reports this user may open (in-app view; works without SMTP)."""
    limit = max(1, min(int(limit), 200))
    with connect(settings) as db:
        rows = db.execute(
            """SELECT o.id,o.event,o.report_id,o.schedule_id,o.run_id,o.detail,o.created_at,o.status,r.name AS report_name
               FROM notification_outbox o JOIN dash_reports r ON r.id=o.report_id ORDER BY o.id DESC LIMIT ?""",
            (limit * 4,),
        ).fetchall()
        visible = {}
        out = []
        for row in rows:
            if row["report_id"] not in visible:
                visible[row["report_id"]] = _can_view(db, user, row["report_id"])
            if visible[row["report_id"]]:
                out.append({**dict(row), "title": EVENTS.get(row["event"], row["event"])})
            if len(out) >= limit:
                break
    return out
