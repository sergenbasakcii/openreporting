"""E-mail delivery of rendered report files (attachments, headers, SMTP)."""

from datetime import timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from zoneinfo import ZoneInfo
from ..domain import parse_utc, validate_emails
from ..postgres_store import assert_worker_ownership
from ..mail_transport import connection as smtp_connection
from .errors import MailSetupError, ReportError

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MIME = {
    "pdf": ("application", "pdf"),
    "xlsx": ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "csv": ("text", "csv"),
    "manifest": ("application", "json"),
}


def send_mail(settings, config, run, files, recipients, partial):
    if not settings.mail_enabled:
        return "disabled"
    recipients = validate_emails(recipients, settings.recipient_domains)
    tz = ZoneInfo(config["timezone"]) if config["timezone"] not in ("UTC", "utc") else timezone.utc
    start = parse_utc(run["period_start"]).astimezone(tz).strftime("%d.%m.%Y %H:%M")
    end = parse_utc(run["period_end"]).astimezone(tz).strftime("%d.%m.%Y %H:%M")
    subject = (config.get("email_subject") or "{report} | {from} – {to}").replace("{report}", config["name"]).replace("{from}", start).replace("{to}", end)
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
