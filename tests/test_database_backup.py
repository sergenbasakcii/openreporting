"""Database backups must preserve WAL writes and never replace user files."""
import sqlite3
from dataclasses import replace

import pytest

from openreporting.config import Settings
from openreporting.db import audit, backup_database, connect, init_db, schema_version, transaction, verify_audit


@pytest.fixture
def settings(tmp_path):
    return replace(Settings.from_env(), data_dir=tmp_path / "state")


def test_live_backup_includes_wal_and_preserves_audit(settings, tmp_path):
    init_db(settings)
    target = tmp_path / "backups" / "state # ç.sqlite3"
    with connect(settings) as live:
        with transaction(live):
            audit(live, "test", "backup.test", "db", "state")
        assert settings.db_path.with_name("state.sqlite3-wal").exists()
        assert backup_database(settings, target) == target.resolve()
    with sqlite3.connect(target) as restored:
        restored.row_factory = sqlite3.Row
        assert schema_version(restored) == 1
        assert restored.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 1
        assert verify_audit(restored) == (True, None)


def test_backup_refuses_existing_target(settings, tmp_path):
    init_db(settings)
    target = tmp_path / "keep.sqlite3"
    target.write_bytes(b"keep existing file")
    with pytest.raises(RuntimeError, match="overwrite"):
        backup_database(settings, target)
    assert target.read_bytes() == b"keep existing file"


def test_backup_refuses_active_data_directory(settings):
    init_db(settings)
    target = settings.data_dir / "backup.sqlite3"
    with pytest.raises(RuntimeError, match="outside"):
        backup_database(settings, target)
    assert not target.exists()


def test_missing_source_does_not_create_database_or_backup(settings, tmp_path):
    target = tmp_path / "backup.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        backup_database(settings, target)
    assert not settings.db_path.exists()
    assert not target.exists()


def test_corrupt_source_removes_only_new_partial_backup(settings, tmp_path):
    settings.data_dir.mkdir()
    settings.db_path.write_bytes(b"not a sqlite database")
    target = tmp_path / "backup.sqlite3"
    with pytest.raises(sqlite3.DatabaseError):
        backup_database(settings, target)
    assert not target.exists()
    assert settings.db_path.read_bytes() == b"not a sqlite database"
