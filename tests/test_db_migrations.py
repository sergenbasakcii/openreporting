"""Schema upgrades must be atomic, repeatable and safe across web workers."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from openreporting import db
from openreporting.config import Settings


@pytest.fixture
def settings(tmp_path):
    return replace(Settings.from_env(), data_dir=tmp_path)


def test_failed_bootstrap_rolls_back_schema_and_version(settings, monkeypatch):
    original = db.MIGRATIONS[1]
    monkeypatch.setitem(db.MIGRATIONS, 1, (*original, "INSERT INTO missing_table VALUES (1)"))
    with pytest.raises(sqlite3.OperationalError):
        db.init_db(settings)
    with db.connect(settings) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    monkeypatch.setitem(db.MIGRATIONS, 1, original)
    db.init_db(settings)


def test_upgrade_failure_preserves_existing_data_and_can_retry(settings, monkeypatch):
    db.init_db(settings)
    with db.connect(settings) as connection, db.transaction(connection):
        db.audit(connection, "test", "before.upgrade", "db", "state")
    monkeypatch.setattr(db, "CURRENT_VERSION", 2)
    monkeypatch.setitem(db.MIGRATIONS, 2, (
        "CREATE TABLE upgrade_probe(id INTEGER PRIMARY KEY)",
        "INSERT INTO missing_table VALUES (1)",
    ))
    with pytest.raises(sqlite3.OperationalError):
        db.init_db(settings)
    with db.connect(settings) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT version FROM schema_versions").fetchall()[0][0] == 1
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='upgrade_probe'").fetchone() is None
        assert db.verify_audit(connection) == (True, None)
        assert connection.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 1
    monkeypatch.setitem(db.MIGRATIONS, 2, ("CREATE TABLE upgrade_probe(id INTEGER PRIMARY KEY)",))
    db.init_db(settings)
    db.init_db(settings)
    with db.connect(settings) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert [r[0] for r in connection.execute("SELECT version FROM schema_versions ORDER BY version")] == [1, 2]


def test_missing_migration_fails_without_version_change(settings, monkeypatch):
    db.init_db(settings)
    monkeypatch.setattr(db, "CURRENT_VERSION", 2)
    with pytest.raises(RuntimeError, match="Missing database migration: 2"):
        db.init_db(settings)
    with db.connect(settings) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1


def test_concurrent_initialisation_records_each_version_once(settings):
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: db.init_db(settings), range(8)))
    with db.connect(settings) as connection:
        assert [r[0] for r in connection.execute("SELECT version FROM schema_versions")] == [1]
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
