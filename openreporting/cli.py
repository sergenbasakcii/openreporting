"""Production operations: admin bootstrap, API, worker, backup and health checks."""
import argparse
import getpass
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .db import audit, connect, init_db, transaction, verify_audit
from .security import create_user, password_hash


def backup(settings, target):
    source_path = settings.db_path
    target = Path(target).resolve()
    if target.exists():
        raise RuntimeError("Refusing to overwrite an existing backup")
    if target.is_relative_to(settings.data_dir):
        raise RuntimeError("Backup should be outside active application data dir")
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source_path) as src, sqlite3.connect(target) as dest:
        src.backup(dest)
        result = dest.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"Backup failed integrity check: {result}")
    os.chmod(target, 0o600)
    print(f"SQLite consistent backup created: {target}")
    print("Important: copy the archive/ directory independently and verify manifest hashes.")


def doctor(settings):
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
        version = db.execute("PRAGMA user_version").fetchone()[0]
        report(version == CURRENT_VERSION, "Veritabanı şeması", f"v{version}")
        integrity = db.execute("PRAGMA quick_check").fetchone()[0]
        report(integrity == "ok", "SQLite bütünlük kontrolü", integrity)
        valid, broken = verify_audit(db)
        report(valid, "Denetim zinciri", "geçerli" if valid else f"bozuk kayıt #{broken}")
        admins = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
        report(admins > 0, "Etkin yönetici hesabı", str(admins))
        worker = db.execute("SELECT last_tick FROM worker_runtime WHERE singleton_id=1").fetchone()
    if worker:
        from .domain import parse_utc
        age = (datetime.now(timezone.utc) - parse_utc(worker["last_tick"])).total_seconds()
        report(age < 120, "Rapor worker sinyali", f"{age:.0f} sn önce")
    else:
        report(False, "Rapor worker sinyali", "worker hiç çalışmadı (systemctl start openreporting-worker)")
    report(not settings.mail_enabled or bool(settings.smtp_host and settings.recipient_domains), "SMTP yapılandırması",
           "etkin" if settings.mail_enabled else "kapalı")
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
        dashboards.save(settings, user, model, message=f"Provisioning: {path.name}", overwrite=True, ds_map=mapping,
                        folder_uid=dashboards.KEEP_FOLDER)
        count += 1
    print(f"{count} dashboard içe aktarıldı")


def main(argv=None):
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
    p_serve = commands.add_parser("serve", help="Serve local API on loopback")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8810)
    p_serve.add_argument("--workers", type=int, default=int(os.getenv("OPENREPORTING_WEB_WORKERS", "1")),
                         help="uvicorn worker processes (Linux: 2-4 recommended behind nginx)")
    p_serve.add_argument("--proxy-headers", action="store_true", default=os.getenv("OPENREPORTING_PROXY_HEADERS", "") in ("1", "true"),
                         help="Trust X-Forwarded-* from the local reverse proxy (127.0.0.1)")
    p_serve.add_argument("--allow-remote", action="store_true",
                         help="Allow a non-loopback bind (containers only; always put TLS in front)")
    commands.add_parser("doctor", help="Check installation: paths, permissions, fonts, schema, worker, datasources")
    p_export = commands.add_parser("export-dashboards", help="Write every dashboard as JSON into a directory")
    p_export.add_argument("directory")
    p_import = commands.add_parser("import-dashboards", help="Import/overwrite dashboards from *.json files (provisioning)")
    p_import.add_argument("directory")
    commands.add_parser("verify-audit", help="Verify audit hash chain")
    p_backup = commands.add_parser("backup", help="Consistent SQLite backup")
    p_backup.add_argument("target")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    settings = Settings.from_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db(settings)
    if args.action == "init":
        print("Empty application initialized. No report templates were added.")
    elif args.action == "create-user":
        password = getpass.getpass("Password (at least 14 chars): ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            raise SystemExit("Passwords do not match")
        print("Created user:", create_user(settings, args.username, password, args.role))
    elif args.action == "reset-password":
        new_password = getpass.getpass("New password (at least 14 chars): ")
        if getpass.getpass("Confirm new password: ") != new_password:
            raise SystemExit("Passwords do not match")
        hashed = password_hash(new_password)
        with connect(settings) as db, transaction(db):
            target = db.execute("SELECT id FROM users WHERE username=?", (args.username.strip().lower(),)).fetchone()
            if not target:
                raise SystemExit("User not found")
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (hashed, target["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?", (target["id"],))
            audit(db, "os-admin", "user.password_rotated", "user", target["id"])
        print("Password rotated; sessions invalidated")
    elif args.action == "disable-user":
        with connect(settings) as db, transaction(db):
            target = db.execute("SELECT id,role,active FROM users WHERE username=?", (args.username.strip().lower(),)).fetchone()
            if not target:
                raise SystemExit("User not found")
            if target["role"] == "admin" and target["active"]:
                remaining = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
                if remaining <= 1:
                    raise SystemExit("Cannot disable the last active admin")
            db.execute("UPDATE users SET active=0 WHERE id=?", (target["id"],))
            db.execute("DELETE FROM sessions WHERE user_id=?", (target["id"],))
            audit(db, "os-admin", "user.disabled", "user", target["id"])
        print("User disabled and sessions invalidated")
    elif args.action in ("worker", "worker-once"):
        from .worker import run_forever
        run_forever(settings, once=args.action == "worker-once")
    elif args.action == "serve":
        if args.host not in ("127.0.0.1", "::1") and not args.allow_remote:
            raise SystemExit("API must bind to loopback; use an approved HTTPS reverse proxy for remote access")
        import uvicorn
        workers = max(1, min(args.workers, 16))
        common = {"host": args.host, "port": args.port, "proxy_headers": args.proxy_headers,
                  "forwarded_allow_ips": "127.0.0.1,::1" if args.proxy_headers else None,
                  "server_header": False, "date_header": True, "timeout_keep_alive": 15}
        if workers > 1 and os.name != "nt":
            # Each worker builds its own app from the same environment.
            uvicorn.run("openreporting.web:create_app", factory=True, workers=workers, **common)
        else:
            from .web import create_app
            uvicorn.run(create_app(settings), workers=1, **common)
    elif args.action == "doctor":
        raise SystemExit(doctor(settings))
    elif args.action == "export-dashboards":
        export_dashboards(settings, args.directory)
    elif args.action == "import-dashboards":
        import_dashboards(settings, args.directory)
    elif args.action == "verify-audit":
        with connect(settings) as db:
            valid, corrupt = verify_audit(db)
        print("PASS" if valid else f"FAIL at audit ID {corrupt}")
        if not valid:
            raise SystemExit(1)
    elif args.action == "backup":
        backup(settings, args.target)


if __name__ == "__main__":
    main()
