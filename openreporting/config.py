import os
from dataclasses import dataclass, field
from pathlib import Path


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"Invalid boolean setting: {name}")
    return value in {"true", "1", "yes"}


def _secret(name: str) -> str:
    """Support mounted secrets without exposing their contents in startup errors."""
    value, filename = os.getenv(name, ""), os.getenv(name + "_FILE", "")
    if value and filename:
        raise ValueError(f"Use either {name} or {name}_FILE")
    if filename:
        try:
            with Path(filename).open(encoding="utf8") as stream:
                value = stream.read(16385)
        except (OSError, UnicodeError):
            raise ValueError(f"Cannot read {name}_FILE") from None
    if len(value) > 16384 or "\x00" in value:
        raise ValueError(f"Invalid secret: {name}")
    return value.rstrip("\r\n") if filename else value


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
    smtp_password: str = field(repr=False)
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
    allow_loopback_datasources: bool = False
    database_url: str = field(default="", repr=False)
    smtp_security: str = ""
    smtp_ca_file: str = ""
    smtp_timeout: int = 30
    smtp_local_hostname: str = ""
    ldap_enabled: bool = False
    ldap_url: str = ""
    ldap_bind_dn: str = ""
    ldap_bind_password: str = field(default="", repr=False)
    ldap_base_dn: str = ""
    ldap_user_filter: str = "(&(objectClass=user)(sAMAccountName={username}))"
    ldap_id_attribute: str = "objectGUID"
    ldap_group_attribute: str = "memberOf"
    ldap_group_roles: str = "{}"
    ldap_ca_file: str = ""
    ldap_timeout: int = 10
    ldap_session_minutes: int = 60
    allowed_hosts: tuple[str, ...] = ()
    mfa_required_roles: tuple[str, ...] = ()

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
            smtp_password=_secret("OPENREPORTING_SMTP_PASSWORD"),
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
            allow_loopback_datasources=_flag("OPENREPORTING_ALLOW_LOOPBACK_DATASOURCES", False),
            database_url=os.getenv("OPENREPORTING_DATABASE_URL", "").strip(),
            smtp_security=os.getenv("OPENREPORTING_SMTP_SECURITY", "").strip().lower(),
            smtp_ca_file=os.getenv("OPENREPORTING_SMTP_CA_FILE", "").strip(),
            smtp_timeout=int(os.getenv("OPENREPORTING_SMTP_TIMEOUT", "30")),
            smtp_local_hostname=os.getenv("OPENREPORTING_SMTP_LOCAL_HOSTNAME", "").strip(),
            ldap_enabled=_flag("OPENREPORTING_LDAP_ENABLED"),
            ldap_url=os.getenv("OPENREPORTING_LDAP_URL", "").strip(),
            ldap_bind_dn=os.getenv("OPENREPORTING_LDAP_BIND_DN", "").strip(),
            ldap_bind_password=_secret("OPENREPORTING_LDAP_BIND_PASSWORD"),
            ldap_base_dn=os.getenv("OPENREPORTING_LDAP_BASE_DN", "").strip(),
            ldap_user_filter=os.getenv("OPENREPORTING_LDAP_USER_FILTER", "(&(objectClass=user)(sAMAccountName={username}))"),
            ldap_id_attribute=os.getenv("OPENREPORTING_LDAP_ID_ATTRIBUTE", "objectGUID").strip(),
            ldap_group_attribute=os.getenv("OPENREPORTING_LDAP_GROUP_ATTRIBUTE", "memberOf").strip(),
            ldap_group_roles=os.getenv("OPENREPORTING_LDAP_GROUP_ROLES", "{}"),
            ldap_ca_file=os.getenv("OPENREPORTING_LDAP_CA_FILE", "").strip(),
            ldap_timeout=int(os.getenv("OPENREPORTING_LDAP_TIMEOUT", "10")),
            ldap_session_minutes=int(os.getenv("OPENREPORTING_LDAP_SESSION_MINUTES", "60")),
            allowed_hosts=tuple(x.strip() for x in os.getenv("OPENREPORTING_ALLOWED_HOSTS", "").split(',') if x.strip()),
            mfa_required_roles=tuple(dict.fromkeys(x.strip() for x in os.getenv('OPENREPORTING_MFA_REQUIRED_ROLES','').split(',') if x.strip())),
        )
        if not 1 <= data.query_concurrency <= 64 or not 10_000 <= data.max_series_points <= 50_000_000:
            raise ValueError("Invalid query concurrency or point budget")
        if not 0 <= data.report_retention_days <= 36500:
            raise ValueError("Invalid report retention")
        from .http_security import trusted_hosts
        trusted_hosts(data)
        if any(role not in {'admin','editor','viewer'} for role in data.mfa_required_roles):
            raise ValueError('Invalid MFA required role policy')
        if not 1 <= data.session_hours <= 168 or not 1 <= data.max_rows <= 1_000_000:
            raise ValueError("Invalid session duration or max rows")
        if not 1000 <= data.query_timeout_ms <= 300_000:
            raise ValueError("Invalid query timeout")
        if data.mail_enabled and (not data.smtp_host or not data.smtp_from or not data.recipient_domains):
            raise ValueError("Mail requires SMTP host, sender and domain allowlist")
        from .mail_transport import validate_settings as validate_smtp
        from .directory_auth import validate_settings as validate_ldap
        validate_smtp(data)
        validate_ldap(data)
        if data.zabbix_url and (not data.zabbix_url.startswith("https://") or not data.zabbix_url.endswith("/api_jsonrpc.php")):
            raise ValueError("Zabbix URL must be HTTPS ending in /api_jsonrpc.php")
        if data.database_url:
            if not data.database_url.startswith(("postgresql://", "postgres://")):
                raise ValueError("OPENREPORTING_DATABASE_URL must be a PostgreSQL URL")
            from psycopg.conninfo import conninfo_to_dict
            try:
                conninfo_to_dict(data.database_url)
            except Exception:
                raise ValueError("Invalid OPENREPORTING_DATABASE_URL") from None
        return data

    @property
    def db_path(self):
        if self.database_url:
            raise RuntimeError("SQLite path is unavailable when PostgreSQL is configured")
        return self.data_dir / "state.sqlite3"

    @property
    def archive_dir(self):
        return self.data_dir / "archive"

