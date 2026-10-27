import os
from dataclasses import dataclass
from pathlib import Path


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"Invalid boolean setting: {name}")
    return value in {"true", "1", "yes"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    secure_cookie: bool
    session_hours: int
    max_rows: int
    query_timeout_ms: int
    mail_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_starttls: bool
    smtp_user: str
    smtp_password: str
    smtp_from: str
    recipient_domains: tuple[str, ...]
    zabbix_url: str = ""
    zabbix_token_file: str = ""
    zabbix_ca_file: str = ""
    secret_key_file: str = ""
    provision_testdata: bool = True
    public_url: str = ""
    query_concurrency: int = 6
    max_series_points: int = 2_000_000
    report_retention_days: int = 365
    allow_http_datasources: bool = False

    @classmethod
    def from_env(cls):
        if os.name == "nt":
            local = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            default_dir = str(Path(local) / "OpenReporting")
        else:
            default_dir = "/var/lib/openreporting"
        data = cls(
            data_dir=Path(os.getenv("OPENREPORTING_DATA_DIR", default_dir)).resolve(),
            secure_cookie=_flag("OPENREPORTING_COOKIE_SECURE", True),
            session_hours=int(os.getenv("OPENREPORTING_SESSION_HOURS", "12")),
            max_rows=int(os.getenv("OPENREPORTING_MAX_ROWS", "200000")),
            query_timeout_ms=int(os.getenv("OPENREPORTING_QUERY_TIMEOUT_MS", "30000")),
            mail_enabled=_flag("OPENREPORTING_MAIL_ENABLED"),
            smtp_host=os.getenv("OPENREPORTING_SMTP_HOST", ""),
            smtp_port=int(os.getenv("OPENREPORTING_SMTP_PORT", "587")),
            smtp_starttls=_flag("OPENREPORTING_SMTP_STARTTLS", True),
            smtp_user=os.getenv("OPENREPORTING_SMTP_USER", ""),
            smtp_password=os.getenv("OPENREPORTING_SMTP_PASSWORD", ""),
            smtp_from=os.getenv("OPENREPORTING_SMTP_FROM", ""),
            recipient_domains=tuple(x.strip().lower() for x in os.getenv("OPENREPORTING_ALLOWED_RECIPIENT_DOMAINS", "").split(",") if x.strip()),
            zabbix_url=os.getenv("OPENREPORTING_ZABBIX_URL", "").strip(),
            zabbix_token_file=os.getenv("OPENREPORTING_ZABBIX_TOKEN_FILE", "").strip(),
            zabbix_ca_file=os.getenv("OPENREPORTING_ZABBIX_CA_FILE", "").strip(),
            secret_key_file=os.getenv("OPENREPORTING_SECRET_KEY_FILE", "").strip(),
            provision_testdata=_flag("OPENREPORTING_PROVISION_TESTDATA", True),
            public_url=os.getenv("OPENREPORTING_PUBLIC_URL", "").strip().rstrip("/"),
            query_concurrency=int(os.getenv("OPENREPORTING_QUERY_CONCURRENCY", "6")),
            max_series_points=int(os.getenv("OPENREPORTING_MAX_SERIES_POINTS", "2000000")),
            report_retention_days=int(os.getenv("OPENREPORTING_REPORT_RETENTION_DAYS", "365")),
            allow_http_datasources=_flag("OPENREPORTING_ALLOW_HTTP_DATASOURCES", False),
        )
        if not 1 <= data.query_concurrency <= 64 or not 10_000 <= data.max_series_points <= 50_000_000:
            raise ValueError("Invalid query concurrency or point budget")
        if not 0 <= data.report_retention_days <= 36500:
            raise ValueError("Invalid report retention")
        if data.public_url and not data.public_url.startswith(("https://", "http://")):
            raise ValueError("OPENREPORTING_PUBLIC_URL must be an http(s) URL")
        if not 1 <= data.session_hours <= 168 or not 1 <= data.max_rows <= 1_000_000:
            raise ValueError("Invalid session duration or max rows")
        if not 1000 <= data.query_timeout_ms <= 300_000:
            raise ValueError("Invalid query timeout")
        if data.mail_enabled and (not data.smtp_host or not data.smtp_from or not data.recipient_domains):
            raise ValueError("Mail requires SMTP host, sender and domain allowlist")
        if data.zabbix_url and (not data.zabbix_url.startswith("https://") or not data.zabbix_url.endswith("/api_jsonrpc.php")):
            raise ValueError("Zabbix URL must be HTTPS ending in /api_jsonrpc.php")
        return data

    @property
    def db_path(self):
        return self.data_dir / "state.sqlite3"

    @property
    def archive_dir(self):
        return self.data_dir / "archive"

