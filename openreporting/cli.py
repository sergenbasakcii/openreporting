"""Production operations: admin bootstrap, API, worker, backup and health checks."""

import argparse
import getpass
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .runtime_settings import effective
from .db import audit, backup_database, check_integrity, connect, init_db, schema_version, transaction, verify_audit
from .security import create_user, password_hash


def backup(settings, target):
    target = backup_database(settings, target)
    print(f"SQLite consistent backup created: {target}")
    print("Important: copy the archive/ directory independently and verify manifest hashes.")


def worker_health(settings, max_age):
    """Probe: never migrates or creates a store; any storage error counts as unhealthy."""
    from .domain import parse_utc

    try:
        if not settings.database_url and not settings.db_path.is_file():
            return 1
        with connect(settings) as db:
            row = db.execute("SELECT last_tick FROM worker_runtime WHERE singleton_id=1").fetchone()
        age = (datetime.now(timezone.utc) - parse_utc(row["last_tick"])).total_seconds() if row else None
    except Exception:  # noqa: BLE001 - a probe reports state, never a traceback
        return 1
    return 0 if age is not None and age <= max_age else 1


def forwarded_allow_ips(value):
    """Proxies whose X-Forwarded-* headers are trusted: exact IPs/networks only, never a wildcard."""
    import ipaddress

    items = [item.strip() for item in (value or "127.0.0.1,::1").split(",") if item.strip()]
    for item in items:
        ipaddress.ip_network(item, strict=False)
    return ",".join(items)


def doctor(settings, *, check_integrations=False):
    """Human-readable installation check; returns a process exit code."""
    import json
    import stat

    problems = 0

    def report(ok, label, detail=""):
        nonlocal problems
        problems += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{' — ' + detail if detail else ''}")

    data = settings.data_dir
    report(data.is_dir(), "Veri dizini", str(data))
    if os.name != "nt" and data.is_dir():
        mode = stat.S_IMODE(data.stat().st_mode)
        report(not mode & 0o007, "Veri dizini başkalarına kapalı", oct(mode))
    try:
        test = data / ".doctor-write-test"
        test.write_text("ok", encoding="utf8")
        test.unlink()
        report(True, "Veri dizinine yazılabiliyor")
    except OSError as exc:
        report(False, "Veri dizinine yazılabiliyor", str(exc))
    from .secrets_store import _fernet, key_path

    try:
        _fernet(settings)
        key_file = key_path(settings)
        report(True, "Şifreleme anahtarı", str(key_file))
        if os.name != "nt":
            key_mode = stat.S_IMODE(key_file.stat().st_mode)
            report(not key_mode & 0o037, "Anahtar dosyası izinleri", f"{oct(key_mode)} (beklenen 0640 veya daha sıkı)")
    except Exception as exc:  # noqa: BLE001
        report(False, "Şifreleme anahtarı", str(exc))
    from .portable import unicode_bold_font_path, unicode_font_path

    try:
        report(True, "PDF yazı tipi", f"{unicode_font_path()} / {unicode_bold_font_path()}")
    except RuntimeError as exc:
        report(False, "PDF yazı tipi", f"{exc} (Ubuntu: apt install fonts-dejavu-core)")
    from .db import CURRENT_VERSION

    with connect(settings) as db:
        version = schema_version(db)
        report(version == CURRENT_VERSION, "Veritabanı şeması", f"v{version}")
        integrity = check_integrity(db)
        label = "PostgreSQL bağlantı ve şema kontrolü" if settings.database_url else "SQLite bütünlük kontrolü"
        report(integrity == "ok", label, integrity)
        valid, broken = verify_audit(db)
        report(valid, "Denetim zinciri", "geçerli" if valid else f"bozuk kayıt #{broken}")
        admins = db.execute("""SELECT COUNT(*) FROM users u WHERE role='admin' AND active=1
                               AND NOT EXISTS(SELECT 1 FROM external_identities e WHERE e.user_id=u.id)""").fetchone()[0]
        report(admins > 0, "Etkin yerel kurtarma yöneticisi", str(admins))
        worker = db.execute("SELECT last_tick FROM worker_runtime WHERE singleton_id=1").fetchone()
    if worker:
        from .domain import parse_utc

        age = (datetime.now(timezone.utc) - parse_utc(worker["last_tick"])).total_seconds()
        report(age < 120, "Rapor worker sinyali", f"{age:.0f} sn önce")
    else:
        report(False, "Rapor worker sinyali", "worker hiç çalışmadı (systemctl start openreporting-worker)")
    report(
        not settings.mail_enabled or bool(settings.smtp_host and settings.recipient_domains),
        "SMTP yapılandırması",
        "etkin" if settings.mail_enabled else "kapalı",
    )
    report(True, "LDAP yapılandırması", "etkin" if settings.ldap_enabled else "kapalı")
    if check_integrations:
        from . import directory_auth, mail_transport

        for enabled, label, check in (
            (settings.ldap_enabled, "LDAP bağlantısı", directory_auth.check_connection),
            (settings.mail_enabled, "SMTP bağlantısı", mail_transport.check_connection),
        ):
            if enabled:
                try:
                    report(True, label, check(settings))
                except Exception:
                    report(False, label, "DNS, port, TLS sertifikası veya hesap doğrulanamadı; sırlar gösterilmedi")
    report(settings.secure_cookie or os.name == "nt", "Güvenli çerez (HTTPS)", str(settings.secure_cookie))
    from . import datasources

    for ds in datasources.list_all(settings):
        try:
            health = datasources.get(settings, ds["uid"]).health()
            report(health.get("status") == "ok", f"Veri kaynağı: {ds['name']}", health.get("message", ""))
        except Exception as exc:  # noqa: BLE001 - network errors vary
            report(False, f"Veri kaynağı: {ds['name']}", str(exc)[:200])
    print(json.dumps({"problems": problems}))
    return 0 if problems == 0 else 1


def export_dashboards(settings, directory):
    import json
    from . import dashboards

    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    admin = {"id": "cli", "role": "admin"}
    count = 0
    for item in dashboards.search(settings, admin, limit=5000):
        model = dashboards.get(settings, item["uid"], admin)["dashboard"]
        model.pop("version", None)
        (target / f"{item['uid']}.json").write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf8")
        count += 1
    print(f"{count} dashboard yazıldı: {target}")


def import_dashboards(settings, directory):
    import json
    from . import dashboards, datasources

    with connect(settings) as db:
        row = db.execute("SELECT id FROM users WHERE role='admin' AND active=1 ORDER BY created_at LIMIT 1").fetchone()
    if not row:
        raise SystemExit("Önce bir yönetici hesabı oluşturun")
    user = {"id": row["id"], "role": "admin"}
    count = 0
    for path in sorted(Path(directory).glob("*.json")):
        model = json.loads(path.read_text(encoding="utf8"))
        mapping = dashboards.import_map(datasources.list_all(settings), model)
        dashboards.save(settings, user, model, message=f"Provisioning: {path.name}", overwrite=True, ds_map=mapping, folder_uid=dashboards.KEEP_FOLDER)
        count += 1
    print(f"{count} dashboard içe aktarıldı")


def build_parser():
    parser = argparse.ArgumentParser(prog="openreporting", description="OpenReporting report management")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("init", help="Initialize empty application state")
    p_user = commands.add_parser("create-user", help="Create a user (interactive password)")
    p_user.add_argument("username")
    p_user.add_argument("--role", choices=["admin", "editor", "viewer"], default="admin")
    p_reset = commands.add_parser("reset-password", help="Rotate password and invalidate all sessions")
    p_reset.add_argument("username")
    p_disable = commands.add_parser("disable-user", help="Disable a user and invalidate all sessions")
    p_disable.add_argument("username")
    commands.add_parser("worker", help="Run the single background worker")
    commands.add_parser("worker-once", help="Run one background worker cycle")
    p_mig = commands.add_parser("migrate-to-postgres", help="Offline one-way copy of a SQLite store into the empty PostgreSQL in OPENREPORTING_DATABASE_URL")
    p_mig.add_argument("--source", required=True, help="Path of the SQLite state.sqlite3 to copy (opened read-only)")
    p_mig.add_argument("--services-stopped", action="store_true", help="Confirm every web process and worker is stopped")
    p_wh = commands.add_parser("worker-health", help="Exit 0 if the worker heartbeat is fresh (container/Kubernetes probe)")
    p_wh.add_argument("--max-age", type=int, default=120, help="Maximum heartbeat age in seconds")
    p_serve = commands.add_parser("serve", help="Serve local API on loopback")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8810)
    p_serve.add_argument(
        "--workers", type=int, default=int(os.getenv("OPENREPORTING_WEB_WORKERS", "1")), help="uvicorn worker processes (Linux: 2-4 recommended behind nginx)"
    )
    p_serve.add_argument(
        "--proxy-headers",
        action="store_true",
        default=os.getenv("OPENREPORTING_PROXY_HEADERS", "") in ("1", "true"),
        help="Trust X-Forwarded-* from the reverse proxy (127.0.0.1, or OPENREPORTING_FORWARDED_ALLOW_IPS)",
    )
    p_serve.add_argument("--allow-remote", action="store_true", help="Allow a non-loopback bind (containers only; always put TLS in front)")
    p_doctor = commands.add_parser("doctor", help="Check installation: paths, permissions, fonts, schema, worker, datasources")
    p_doctor.add_argument("--check-integrations", action="store_true", help="Check LDAP and SMTP TLS/authentication; never sends mail")
    p_ldap = commands.add_parser("check-ldap", help="Test a directory user's password and group mapping without provisioning a user")
    p_ldap.add_argument("username")
    p_export = commands.add_parser("export-dashboards", help="Write every dashboard as JSON into a directory")
    p_export.add_argument("directory")
    p_import = commands.add_parser("import-dashboards", help="Import/overwrite dashboards from *.json files (provisioning)")
    p_import.add_argument("directory")
    commands.add_parser("verify-audit", help="Verify audit hash chain")
    commands.add_parser("check-postgres", help="Read-only PostgreSQL schema, role and transport preflight; never initializes or migrates")
    p_backup = commands.add_parser("backup", help="Consistent SQLite backup")
    p_backup.add_argument("target")
    p_verify = commands.add_parser("verify-backup", help="Verify backup DB, audit, report files, logos and key in disposable storage")
    p_verify.add_argument("directory")
    p_verify.add_argument("--key-file", help="Separately held encryption key (never printed or copied into the backup)")
    p_verify.add_argument("--max-unpacked-mb", type=int, default=2048)
    p_verify.add_argument("--require-logos", action="store_true")
    p_rotate = commands.add_parser("prepare-key-rotation", help="Create a new versioned key ring; active key and database stay unchanged")
    p_rotate.add_argument("--output", required=True)
    p_rekey = commands.add_parser("rekey-secrets", help="Offline SQLite maintenance: re-encrypt datasource credentials to the prepared primary key")
    p_rekey.add_argument("--services-stopped", action="store_true", help="Acknowledge every web process and worker is stopped for maintenance")
    p_retire = commands.add_parser("prepare-key-retirement", help="Create a primary-only ring after verifying every stored credential uses it")
    p_retire.add_argument("--output", required=True)
    p_retire.add_argument("--services-stopped", action="store_true")
    p_mfa = commands.add_parser("reset-mfa", help="OS-operator factor recovery; revoke sessions without changing password")
    p_mfa.add_argument("username")
    p_mfa.add_argument("--reason", required=True, choices=["lost-device", "compromise", "recovery"])
    return parser


def _print_json(result, **kwargs):
    import json

    print(json.dumps(result, **kwargs))


# --- commands that run before any settings are loaded ---------------------------------------


def _cmd_migrate_to_postgres(args):
    # The target must still be empty when the copy starts: never initialise it first.
    from .pg_migrate import MigrationError, migrate

    try:
        result = migrate(args.source, os.getenv("OPENREPORTING_DATABASE_URL", "").strip(), services_stopped=args.services_stopped)
    except MigrationError as exc:
        raise SystemExit(str(exc)) from None
    _print_json(result, indent=2)


def _cmd_worker_health(args):
    raise SystemExit(worker_health(Settings.from_env(), args.max_age))


def _cmd_verify_backup(args):
    # Never initialise, migrate, replace or connect to the live application state.
    from .backup_verify import BackupVerificationError, verify_backup

    try:
        result = verify_backup(args.directory, key_file=args.key_file, max_unpacked_bytes=args.max_unpacked_mb * 1024**2, require_logos=args.require_logos)
    except BackupVerificationError as exc:
        raise SystemExit(str(exc)) from None
    _print_json(result)


# --- maintenance commands: settings, but never an implicit migration ------------------------


def _cmd_check_postgres(args, settings):
    from .postgres_check import check

    result = check(settings)
    _print_json(result)
    raise SystemExit(0 if result["ok"] else 2)


def _cmd_reset_mfa(args, settings):
    import sqlite3

    from psycopg import Error as PostgresError

    from .mfa import admin_reset

    try:
        result = admin_reset(settings, args.username, args.reason)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    except (sqlite3.Error, PostgresError, OSError):
        raise SystemExit("Factor recovery storage unavailable; no implicit migration or replacement performed") from None
    _print_json(result)


def _cmd_key_maintenance(args, settings):
    from .key_rotation import prepare_retirement, prepare_rotation, rekey_secrets
    from .secrets_store import SecretError

    operations = {
        "prepare-key-rotation": lambda: prepare_rotation(settings, args.output),
        "prepare-key-retirement": lambda: prepare_retirement(settings, args.output, services_stopped=args.services_stopped),
        "rekey-secrets": lambda: rekey_secrets(settings, services_stopped=args.services_stopped),
    }
    try:
        result = operations[args.action]()
    except SecretError as exc:
        raise SystemExit(str(exc)) from None
    _print_json(result)


# --- application commands: the schema is initialised/upgraded first -------------------------


def _cmd_init(args, settings):
    print("Empty application initialized. No report templates were added.")


def _new_password(prompt):
    password = getpass.getpass(f"{prompt} (at least 14 chars): ")
    if getpass.getpass("Confirm password: ") != password:
        raise SystemExit("Passwords do not match")
    return password


def _cmd_create_user(args, settings):
    print("Created user:", create_user(settings, args.username, _new_password("Password"), args.role))


def _find_user(db, username, columns="id"):
    target = db.execute(f"SELECT {columns} FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
    if not target:
        raise SystemExit("User not found")
    return target


def _is_external(db, user_id):
    return db.execute("SELECT 1 FROM external_identities WHERE user_id=?", (user_id,)).fetchone() is not None


def _cmd_reset_password(args, settings):
    hashed = password_hash(_new_password("New password"))
    with connect(settings) as db, transaction(db):
        target = _find_user(db, args.username, "id,password_hash")
        if _is_external(db, target["id"]):
            raise SystemExit("LDAP passwords must be changed in the directory")
        if target["password_hash"] == "!service":
            raise SystemExit("Service accounts have no password; issue an API token instead")
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (hashed, target["id"]))
        db.execute("DELETE FROM sessions WHERE user_id=?", (target["id"],))
        audit(db, "os-admin", "user.password_rotated", "user", target["id"])
    print("Password rotated; sessions invalidated")


def _cmd_disable_user(args, settings):
    with connect(settings) as db, transaction(db):
        target = _find_user(db, args.username, "id,role,active")
        if target["role"] == "admin" and target["active"]:
            if db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0] <= 1:
                raise SystemExit("Cannot disable the last active admin")
            if not _is_external(db, target["id"]):
                remaining_local = db.execute(
                    """SELECT COUNT(*) FROM users u WHERE role='admin' AND active=1
                    AND NOT EXISTS(SELECT 1 FROM external_identities e WHERE e.user_id=u.id)"""
                ).fetchone()[0]
                if remaining_local <= 1:
                    raise SystemExit("Cannot disable the last local recovery admin")
        db.execute("UPDATE users SET active=0 WHERE id=?", (target["id"],))
        db.execute("DELETE FROM sessions WHERE user_id=?", (target["id"],))
        audit(db, "os-admin", "user.disabled", "user", target["id"])
    print("User disabled and sessions invalidated")


def _cmd_worker(args, settings):
    from .worker import run_forever

    run_forever(settings, once=args.action == "worker-once")


def _cmd_serve(args, settings):
    if args.host not in ("127.0.0.1", "::1") and not args.allow_remote:
        raise SystemExit("API must bind to loopback; use an approved HTTPS reverse proxy for remote access")
    import uvicorn

    from .http_telemetry import logging_config

    workers = max(1, min(args.workers, 16))
    try:
        trusted_proxies = forwarded_allow_ips(os.getenv("OPENREPORTING_FORWARDED_ALLOW_IPS", ""))
    except ValueError:
        raise SystemExit("OPENREPORTING_FORWARDED_ALLOW_IPS must list exact proxy IP addresses or networks") from None
    common = {
        "host": args.host,
        "port": args.port,
        "proxy_headers": args.proxy_headers,
        "forwarded_allow_ips": trusted_proxies if args.proxy_headers else None,
        "server_header": False,
        "date_header": True,
        "timeout_keep_alive": 15,
        "access_log": False,
        "log_config": logging_config(),
    }
    if workers > 1 and os.name != "nt":
        # Each worker builds its own app from the same environment.
        uvicorn.run("openreporting.web:create_app", factory=True, workers=workers, **common)
    else:
        from .web import create_app

        uvicorn.run(create_app(settings), workers=1, **common)


def _cmd_doctor(args, settings):
    raise SystemExit(doctor(effective(settings), check_integrations=args.check_integrations))


def _cmd_check_ldap(args, settings):
    from .directory_auth import DirectoryUnavailable
    from .directory_auth import authenticate as directory_login

    try:
        result = directory_login(effective(settings), args.username.strip().lower(), getpass.getpass("Directory password: "))
    except DirectoryUnavailable as exc:
        raise SystemExit(str(exc)) from None
    if result is None:
        raise SystemExit("LDAP authentication or group admission failed")
    print(f"LDAP authentication and group mapping verified; role={result.role}. No account or session created.")


def _cmd_verify_audit(args, settings):
    with connect(settings) as db:
        valid, corrupt = verify_audit(db)
    print("PASS" if valid else f"FAIL at audit ID {corrupt}")
    if not valid:
        raise SystemExit(1)


# The stage decides what runs before a command: "raw" loads nothing, "maintenance" loads settings
# without touching the schema, "app" initialises/upgrades the schema first.
COMMANDS = {
    "migrate-to-postgres": ("raw", _cmd_migrate_to_postgres),
    "worker-health": ("raw", _cmd_worker_health),
    "verify-backup": ("raw", _cmd_verify_backup),
    "check-postgres": ("maintenance", _cmd_check_postgres),
    "reset-mfa": ("maintenance", _cmd_reset_mfa),
    "prepare-key-rotation": ("maintenance", _cmd_key_maintenance),
    "rekey-secrets": ("maintenance", _cmd_key_maintenance),
    "prepare-key-retirement": ("maintenance", _cmd_key_maintenance),
    "init": ("app", _cmd_init),
    "create-user": ("app", _cmd_create_user),
    "reset-password": ("app", _cmd_reset_password),
    "disable-user": ("app", _cmd_disable_user),
    "worker": ("app", _cmd_worker),
    "worker-once": ("app", _cmd_worker),
    "serve": ("app", _cmd_serve),
    "doctor": ("app", _cmd_doctor),
    "check-ldap": ("app", _cmd_check_ldap),
    "export-dashboards": ("app", lambda args, settings: export_dashboards(settings, args.directory)),
    "import-dashboards": ("app", lambda args, settings: import_dashboards(settings, args.directory)),
    "verify-audit": ("app", _cmd_verify_audit),
    "backup": ("app", lambda args, settings: backup(settings, args.target)),
}


def main(argv=None):
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    stage, command = COMMANDS[args.action]
    if stage == "raw":
        return command(args)
    settings = Settings.from_env()
    if stage == "app":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        init_db(settings)
    return command(args, settings)


if __name__ == "__main__":
    main()
