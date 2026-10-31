"""Verified TLS SMTP transport shared by reports and non-delivery diagnostics."""
import re
import smtplib
import ssl
from contextlib import contextmanager
from pathlib import Path


def security_mode(settings):
    return settings.smtp_security or ("starttls" if settings.smtp_starttls else "none")


def validate_settings(settings):
    mode = security_mode(settings)
    if mode not in {"starttls", "tls", "none"}:
        raise ValueError("SMTP_SECURITY must be starttls or tls")
    if not 1 <= settings.smtp_port <= 65535 or not 1 <= settings.smtp_timeout <= 120:
        raise ValueError("Invalid SMTP port or timeout")
    if settings.mail_enabled:
        if mode not in {"starttls", "tls"}:
            raise ValueError("SMTP requires verified TLS (starttls or tls)")
        if not re.fullmatch(r"[^\s/@:]+", settings.smtp_host):
            raise ValueError("SMTP_HOST must be a hostname or IP address")
        from .domain import validate_emails
        validate_emails([settings.smtp_from], (settings.smtp_from.lower().rsplit("@", 1)[-1],))
        if not settings.recipient_domains or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}", d) for d in settings.recipient_domains):
            raise ValueError("Invalid SMTP recipient domain allowlist")
        if bool(settings.smtp_user) != bool(settings.smtp_password):
            raise ValueError("SMTP_USER and SMTP_PASSWORD must both be set, or both empty for a TLS relay")
    if settings.smtp_local_hostname and not re.fullmatch(r"[A-Za-z0-9.-]+", settings.smtp_local_hostname):
        raise ValueError("Invalid SMTP_LOCAL_HOSTNAME")
    if settings.smtp_ca_file and not Path(settings.smtp_ca_file).is_file():
        raise ValueError("SMTP_CA_FILE is unavailable")


@contextmanager
def connection(settings):
    validate_settings(settings)
    if not settings.mail_enabled:
        raise ValueError("SMTP is disabled")
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if settings.smtp_ca_file:
        context.load_verify_locations(cafile=settings.smtp_ca_file)
    options = {"host": settings.smtp_host, "port": settings.smtp_port, "timeout": settings.smtp_timeout}
    if settings.smtp_local_hostname:
        options["local_hostname"] = settings.smtp_local_hostname
    smtp = smtplib.SMTP_SSL(context=context, **options) if security_mode(settings) == "tls" else smtplib.SMTP(**options)
    try:
        code, _ = smtp.ehlo()
        if code != 250:
            raise smtplib.SMTPHeloError(code, b"EHLO rejected")
        if security_mode(settings) == "starttls":
            smtp.starttls(context=context)
            code, _ = smtp.ehlo()
            if code != 250:
                raise smtplib.SMTPHeloError(code, b"EHLO rejected after TLS")
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        yield smtp
    finally:
        # A QUIT error after a successful DATA must not misclassify a delivered message.
        smtp.close()


def check_connection(settings):
    """TLS + optional authentication + NOOP; never MAIL/RCPT/DATA."""
    with connection(settings) as smtp:
        code, _ = smtp.noop()
        if code != 250:
            raise smtplib.SMTPResponseException(code, b"NOOP rejected")
    return "TLS ve SMTP bağlantısı doğrulandı; e-posta gönderilmedi"
