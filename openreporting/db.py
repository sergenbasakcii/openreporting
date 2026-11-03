import hashlib
import json
from datetime import datetime, timezone

from .config import Settings
from . import postgres_store, sqlite_store


def connect(settings):
    if settings.database_url:
        postgres_store.assert_worker_ownership()
        return postgres_store.connect(settings.database_url, timeout_ms=settings.query_timeout_ms)
    return sqlite_store.connect(settings)


def transaction(db):
    backend = postgres_store if isinstance(db, postgres_store.Connection) else sqlite_store
    return backend.transaction(db)


def schema_version(db):
    backend = postgres_store if isinstance(db, postgres_store.Connection) else sqlite_store
    return backend.schema_version(db)


def check_integrity(db, *, full=False):
    if isinstance(db, postgres_store.Connection):
        # Connectivity/schema metadata only; never claim a physical PostgreSQL scan.
        db.execute("SELECT 1").fetchone()
        schema_version(db)
        return "ok"
    return sqlite_store.check_integrity(db, full=full)


def backup_database(settings, target):
    if settings.database_url:
        raise RuntimeError("PostgreSQL backup requires pg_dump; file backup is disabled for this backend")
    return sqlite_store.backup_database(settings, target)


def has_encrypted_secrets(settings):
    if settings.database_url:
        with connect(settings) as db:
            if db.execute("SELECT 1 FROM datasources WHERE secure_json<>'' LIMIT 1").fetchone() is not None:
                return True
            for table, column in (("user_mfa", "secret_json"), ("app_settings", "secure_json")):
                exists = db.execute(f"SELECT to_regclass('{table}')").fetchone()[0]
                if exists and db.execute(f"SELECT 1 FROM {table} WHERE {column}<>'' LIMIT 1").fetchone():
                    return True
            return False
    return sqlite_store.has_encrypted_secrets(settings)


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(
 id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('admin','editor','viewer')),
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, email TEXT NOT NULL DEFAULT '',
 display_name TEXT NOT NULL DEFAULT '', last_login_at TEXT);
CREATE TABLE IF NOT EXISTS sessions(
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 csrf_hash TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS login_failures(
 username TEXT PRIMARY KEY, count INTEGER NOT NULL, last_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
 id INTEGER PRIMARY KEY AUTOINCREMENT, happened_at TEXT NOT NULL,
 actor TEXT NOT NULL, action TEXT NOT NULL, object_type TEXT NOT NULL,
 object_id TEXT NOT NULL, details TEXT NOT NULL,
 prev_hash TEXT NOT NULL, entry_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS worker_runtime(
 singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
 worker_id TEXT NOT NULL, started_at TEXT NOT NULL, last_tick TEXT NOT NULL,
 tick_count INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS user_prefs(
 user_id TEXT PRIMARY KEY REFERENCES users(id), theme TEXT NOT NULL DEFAULT 'dark',
 timezone TEXT NOT NULL DEFAULT 'browser', home_dashboard_uid TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS datasources(
 id TEXT PRIMARY KEY, uid TEXT NOT NULL UNIQUE, name TEXT NOT NULL UNIQUE,
 type TEXT NOT NULL CHECK(type IN ('zabbix','postgres','testdata')),
 url TEXT NOT NULL DEFAULT '', json_data TEXT NOT NULL DEFAULT '{}', secure_json TEXT NOT NULL DEFAULT '',
 is_default INTEGER NOT NULL DEFAULT 0, provisioned INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS folders(
 id TEXT PRIMARY KEY, uid TEXT NOT NULL UNIQUE, title TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dashboards(
 id TEXT PRIMARY KEY, uid TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
 folder_id TEXT REFERENCES folders(id), tags_json TEXT NOT NULL DEFAULT '[]',
 data_json TEXT NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS dashboards_folder_idx ON dashboards(folder_id,title);
CREATE TABLE IF NOT EXISTS dashboard_versions(
 dashboard_id TEXT NOT NULL REFERENCES dashboards(id) ON DELETE CASCADE, version INTEGER NOT NULL,
 data_json TEXT NOT NULL, message TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
 created_by TEXT NOT NULL, PRIMARY KEY(dashboard_id,version));
CREATE TABLE IF NOT EXISTS dashboard_stars(
 user_id TEXT NOT NULL REFERENCES users(id), dashboard_id TEXT NOT NULL REFERENCES dashboards(id) ON DELETE CASCADE,
 PRIMARY KEY(user_id,dashboard_id));
CREATE TABLE IF NOT EXISTS annotations(
 id TEXT PRIMARY KEY, dashboard_uid TEXT, panel_id INTEGER, time_ms INTEGER NOT NULL, time_end_ms INTEGER,
 text TEXT NOT NULL, tags_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, created_by TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS annotations_dash_idx ON annotations(dashboard_uid,time_ms);
CREATE TABLE IF NOT EXISTS dash_reports(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, dashboard_uid TEXT NOT NULL,
 config_json TEXT NOT NULL, config_sha256 TEXT NOT NULL, revision INTEGER NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dash_report_schedules(
 id TEXT PRIMARY KEY, report_id TEXT NOT NULL REFERENCES dash_reports(id) ON DELETE CASCADE,
 cadence TEXT NOT NULL CHECK(cadence IN ('hourly','daily','weekly','monthly','yearly')),
 timezone TEXT NOT NULL, hour INTEGER NOT NULL, minute INTEGER NOT NULL,
 weekday INTEGER NOT NULL DEFAULT 0, month_day INTEGER NOT NULL DEFAULT 1,
 range_mode TEXT NOT NULL DEFAULT 'previous_period', recipients_json TEXT NOT NULL DEFAULT '[]',
 enabled INTEGER NOT NULL DEFAULT 0, next_due TEXT NOT NULL, last_run_id TEXT,
 created_by TEXT NOT NULL, updated_at TEXT NOT NULL, approved_config_sha256 TEXT,
 approved_dashboard_version INTEGER, approved_by TEXT);
CREATE INDEX IF NOT EXISTS dash_report_schedules_due_idx ON dash_report_schedules(enabled,next_due);
CREATE TABLE IF NOT EXISTS dash_report_runs(
 id TEXT PRIMARY KEY, report_id TEXT NOT NULL REFERENCES dash_reports(id) ON DELETE CASCADE,
 schedule_id TEXT, revision INTEGER NOT NULL, config_sha256 TEXT NOT NULL,
 period_start TEXT NOT NULL, period_end TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL, delivery_status TEXT NOT NULL DEFAULT 'not_requested',
 recipients_json TEXT NOT NULL DEFAULT '[]', created_by TEXT, created_at TEXT NOT NULL,
 started_at TEXT, finished_at TEXT, error TEXT, owner TEXT, lease_until TEXT,
 files_json TEXT NOT NULL DEFAULT '{}', warnings_json TEXT NOT NULL DEFAULT '[]');
CREATE INDEX IF NOT EXISTS dash_report_runs_queue_idx ON dash_report_runs(status,created_at);
CREATE INDEX IF NOT EXISTS dash_report_runs_report_idx ON dash_report_runs(report_id,created_at);
"""

# Schema changes are appended as numbered steps; a database is upgraded step by step on start.
CURRENT_VERSION = 10

# Each migration is a tuple of complete statements, executed in one transaction.
# Only the initial schema is split here; later migrations may contain triggers or
# other statements with internal semicolons and must be supplied explicitly.
MIGRATIONS = {1: tuple(statement.strip() for statement in SCHEMA.split(";") if statement.strip())}
_SOURCE_TYPES = "'zabbix','postgres','testdata','prometheus','loki','httpjson','csv'"
_source_schema = next(s for s in MIGRATIONS[1] if s.startswith("CREATE TABLE IF NOT EXISTS datasources("))
_source_schema = _source_schema.replace("datasources(", "datasources_v2(", 1).replace("'zabbix','postgres','testdata'", _SOURCE_TYPES)
MIGRATIONS[2] = (
    _source_schema,
    "INSERT INTO datasources_v2 SELECT * FROM datasources",
    "DROP TABLE datasources",
    "ALTER TABLE datasources_v2 RENAME TO datasources",
)
POSTGRES_MIGRATIONS = {
    1: postgres_store.bootstrap_statements(MIGRATIONS[1]),
    2: (
        "ALTER TABLE datasources DROP CONSTRAINT datasources_type_check",
        f"ALTER TABLE datasources ADD CONSTRAINT datasources_type_check CHECK(type IN ({_SOURCE_TYPES}))",
    ),
}
MIGRATIONS[3] = (
    """CREATE TABLE external_identities(
 user_id TEXT PRIMARY KEY REFERENCES users(id), provider TEXT NOT NULL CHECK(provider='ldap'),
 subject TEXT NOT NULL, UNIQUE(provider,subject))""",
)
POSTGRES_MIGRATIONS[3] = postgres_store.widen_integers(MIGRATIONS[3])
MIGRATIONS[4] = (
    """CREATE TABLE user_mfa(
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 secret_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
 pending_expires_at TEXT NOT NULL DEFAULT '', setup_hash TEXT NOT NULL DEFAULT '', last_counter INTEGER NOT NULL DEFAULT -1,
 recovery_hashes TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL)""",
    """CREATE TABLE mfa_sessions(token_hash TEXT PRIMARY KEY REFERENCES sessions(token_hash) ON DELETE CASCADE)""",
)
POSTGRES_MIGRATIONS[4] = postgres_store.widen_integers(MIGRATIONS[4])
MIGRATIONS[5] = (
    """CREATE TABLE folder_policy(
 folder_id TEXT PRIMARY KEY REFERENCES folders(id) ON DELETE CASCADE,
 restricted INTEGER NOT NULL DEFAULT 0 CHECK(restricted IN (0,1)), revision INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE folder_user_grants(
 folder_id TEXT NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 permission TEXT NOT NULL CHECK(permission IN ('view','edit')), PRIMARY KEY(folder_id,user_id))""",
)
POSTGRES_MIGRATIONS[5] = postgres_store.widen_integers(MIGRATIONS[5])
# Admin-UI settings layered over the environment file; secrets are Fernet-sealed per scope.
# Rows are never deleted: a reset clears values and bumps the revision so caches stay monotonic.
MIGRATIONS[6] = (
    """CREATE TABLE app_settings(
 scope TEXT PRIMARY KEY CHECK(scope IN ('mail','ldap','security','limits','sources')),
 values_json TEXT NOT NULL DEFAULT '{}', secure_json TEXT NOT NULL DEFAULT '',
 revision INTEGER NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL)""",
)
POSTGRES_MIGRATIONS[6] = postgres_store.widen_integers(MIGRATIONS[6])
# Report pipeline notifications: written in the same transaction as the event, delivered by the worker.
_OUTBOX = """CREATE TABLE notification_outbox(
 id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL, report_id TEXT NOT NULL,
 schedule_id TEXT, run_id TEXT, detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sent','skipped','failed')),
 attempts INTEGER NOT NULL DEFAULT 0, sent_at TEXT)"""
MIGRATIONS[7] = (
    _OUTBOX,
    "CREATE INDEX notification_outbox_pending_idx ON notification_outbox(status,id)",
    "CREATE INDEX notification_outbox_report_idx ON notification_outbox(report_id,created_at)",
    "ALTER TABLE user_prefs ADD COLUMN notify_report_failures INTEGER NOT NULL DEFAULT 1 CHECK(notify_report_failures IN (0,1))",
)
POSTGRES_MIGRATIONS[7] = postgres_store.widen_integers(
    (_OUTBOX.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"),) + MIGRATIONS[7][1:]
)
# API tokens for service accounts, and datasource types from installed plugins ("x-" prefix).
_TOKENS = """CREATE TABLE api_tokens(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, name TEXT NOT NULL,
 prefix TEXT NOT NULL UNIQUE, token_hash TEXT NOT NULL UNIQUE, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT)"""
_PLUGIN_TYPES = f"type IN ({_SOURCE_TYPES}) OR type LIKE 'x-%'"
_source_schema_v3 = (
    next(s for s in MIGRATIONS[1] if s.startswith("CREATE TABLE IF NOT EXISTS datasources("))
    .replace("datasources(", "datasources_v3(", 1)
    .replace("type IN ('zabbix','postgres','testdata')", _PLUGIN_TYPES)
)
MIGRATIONS[8] = (
    _TOKENS,
    "CREATE INDEX api_tokens_user_idx ON api_tokens(user_id)",
    _source_schema_v3,
    "INSERT INTO datasources_v3 SELECT * FROM datasources",
    "DROP TABLE datasources",
    "ALTER TABLE datasources_v3 RENAME TO datasources",
)
POSTGRES_MIGRATIONS[8] = postgres_store.widen_integers(
    (
        _TOKENS,
        "CREATE INDEX api_tokens_user_idx ON api_tokens(user_id)",
        "ALTER TABLE datasources DROP CONSTRAINT datasources_type_check",
        f"ALTER TABLE datasources ADD CONSTRAINT datasources_type_check CHECK({_PLUGIN_TYPES})",
    )
)

# More built-in datasource types (data lake, search, time-series stores).
_SOURCE_TYPES_V4 = _SOURCE_TYPES + ",'trino','databricks','clickhouse','elasticsearch','influxdb','graphite'"
_PLUGIN_TYPES_V4 = f"type IN ({_SOURCE_TYPES_V4}) OR type LIKE 'x-%'"
_source_schema_v4 = _source_schema_v3.replace("datasources_v3(", "datasources_v4(", 1).replace(_PLUGIN_TYPES, _PLUGIN_TYPES_V4)
MIGRATIONS[9] = (
    _source_schema_v4,
    "INSERT INTO datasources_v4 SELECT * FROM datasources",
    "DROP TABLE datasources",
    "ALTER TABLE datasources_v4 RENAME TO datasources",
)
POSTGRES_MIGRATIONS[9] = (
    "ALTER TABLE datasources DROP CONSTRAINT datasources_type_check",
    f"ALTER TABLE datasources ADD CONSTRAINT datasources_type_check CHECK({_PLUGIN_TYPES_V4})",
)

# Teams (user groups) with folder grants, and per-dashboard policies granted to users or teams.
_TEAMS = (
    """CREATE TABLE teams(
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, created_by TEXT NOT NULL)""",
    """CREATE TABLE team_members(
 team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, PRIMARY KEY(team_id,user_id))""",
    "CREATE INDEX team_members_user_idx ON team_members(user_id)",
    """CREATE TABLE folder_team_grants(
 folder_id TEXT NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
 team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
 permission TEXT NOT NULL CHECK(permission IN ('view','edit')), PRIMARY KEY(folder_id,team_id))""",
    """CREATE TABLE dashboard_policy(
 dashboard_id TEXT PRIMARY KEY REFERENCES dashboards(id) ON DELETE CASCADE,
 restricted INTEGER NOT NULL DEFAULT 0 CHECK(restricted IN (0,1)), revision INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE dashboard_grants(
 dashboard_id TEXT NOT NULL REFERENCES dashboards(id) ON DELETE CASCADE,
 principal_type TEXT NOT NULL CHECK(principal_type IN ('user','team')), principal_id TEXT NOT NULL,
 permission TEXT NOT NULL CHECK(permission IN ('view','edit')), PRIMARY KEY(dashboard_id,principal_type,principal_id))""",
    "CREATE INDEX dashboard_grants_principal_idx ON dashboard_grants(principal_type,principal_id)",
)
MIGRATIONS[10] = _TEAMS
POSTGRES_MIGRATIONS[10] = postgres_store.widen_integers(_TEAMS)


def init_db(settings: Settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings.archive_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if settings.database_url:
        with connect(settings) as db:
            postgres_store.init_schema(db, POSTGRES_MIGRATIONS, CURRENT_VERSION)
        return
    with connect(settings) as db, transaction(db):
        # Acquire the write lock before reading the version: web workers may
        # initialise the same database concurrently during application startup.
        version = schema_version(db)
        if version > CURRENT_VERSION:
            raise RuntimeError("This application cannot open a newer database schema")
        for target in range(version + 1, CURRENT_VERSION + 1):
            statements = MIGRATIONS.get(target)
            if statements is None:
                raise RuntimeError(f"Missing database migration: {target}")
            for statement in statements:
                db.execute(statement)
            db.execute("INSERT INTO schema_versions(version,applied_at) VALUES (?,?)", (target, utcnow()))
            sqlite_store.set_schema_version(db, target)


def audit(db, actor, action, object_type, object_id, details=None):
    prev_row = db.execute("SELECT entry_hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    prev = prev_row[0] if prev_row else "0" * 64
    payload = (utcnow(), actor, action, object_type, object_id, json.dumps(details or {}, sort_keys=True, ensure_ascii=False))
    digest = hashlib.sha256(json.dumps([prev, *payload], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    db.execute(
        "INSERT INTO audit(happened_at,actor,action,object_type,object_id,details,prev_hash,entry_hash) VALUES(?,?,?,?,?,?,?,?)", (*payload, prev, digest)
    )


def verify_audit(db):
    previous = "0" * 64
    for r in db.execute("SELECT * FROM audit ORDER BY id"):
        body = [r[k] for k in ("happened_at", "actor", "action", "object_type", "object_id", "details")]
        digest = hashlib.sha256(json.dumps([previous, *body], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        if r["prev_hash"] != previous or r["entry_hash"] != digest:
            return False, r["id"]
        previous = digest
    return True, None
