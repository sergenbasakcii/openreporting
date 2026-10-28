"""SQLite driver operations for the application database.

Keep SQLite connection details here so the application-facing db module and
operations commands can gain another backend without duplicating driver logic.
"""
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .config import Settings


def schema_version(db):
    return db.execute("PRAGMA user_version").fetchone()[0]


def set_schema_version(db, version):
    if type(version) is not int or not 0 <= version <= 2_147_483_647:
        raise ValueError("Invalid database schema version")
    db.execute(f"PRAGMA user_version={version}")


def check_integrity(db, *, full=False):
    pragma = "integrity_check" if full else "quick_check"
    return "; ".join(str(row[0]) for row in db.execute(f"PRAGMA {pragma}"))


def backup_database(settings, target):
    """Copy a live WAL database without creating a missing source or overwriting a file."""
    target = Path(target).resolve()
    if target.is_relative_to(settings.data_dir.resolve()):
        raise RuntimeError("Backup should be outside active application data dir")
    if target.exists():
        raise RuntimeError("Refusing to overwrite an existing backup")
    source_uri = settings.db_path.resolve().as_uri() + "?mode=ro"
    # Open the source first so a missing/unreadable source never leaves an empty backup.
    with _connect_uri(source_uri) as src:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise RuntimeError("Refusing to overwrite an existing backup") from exc
        os.close(fd)
        try:
            with _connect_uri(target.resolve().as_uri() + "?mode=rw") as dest:
                src.backup(dest)
                result = check_integrity(dest, full=True)
                if result != "ok":
                    raise RuntimeError(f"Backup failed integrity check: {result}")
        except BaseException:
            target.unlink(missing_ok=True)
            raise
    return target


@contextmanager
def _connect_uri(uri):
    """Open a URI with an explicit access mode; always close the handle."""
    db = sqlite3.connect(uri, uri=True, timeout=20)
    try:
        yield db
    finally:
        db.close()


@contextmanager
def connect(settings: Settings):
    db = sqlite3.connect(settings.db_path, timeout=20, isolation_level=None)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=20000")
        # Switching a fresh database to WAL can return SQLITE_BUSY immediately
        # despite busy_timeout when several workers open it at the same time.
        deadline = time.monotonic() + 20
        while True:
            try:
                db.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError as exc:
                if getattr(exc, "sqlite_errorcode", None) != sqlite3.SQLITE_BUSY or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        yield db
    finally:
        db.close()


@contextmanager
def transaction(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def has_encrypted_secrets(settings: Settings):
    """Inspect stored credentials without creating or modifying application data.

    An unreadable existing database must propagate an error: callers must not
    interpret an inspection failure as permission to replace a missing key.
    """
    path = settings.db_path
    if not path.exists():
        return False
    uri = path.resolve().as_uri() + "?mode=ro"
    with _connect_uri(uri) as db:
        return db.execute("SELECT 1 FROM datasources WHERE secure_json<>'' LIMIT 1").fetchone() is not None
