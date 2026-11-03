"""Explicit backend selection must never silently use an unrelated SQLite file."""

from dataclasses import replace

import pytest

from openreporting.config import Settings


def test_postgres_url_is_explicit_and_not_in_settings_repr(monkeypatch):
    monkeypatch.setenv("OPENREPORTING_DATABASE_URL", "postgresql://test:synthetic-password@example.com/test")
    settings = Settings.from_env()
    assert settings.database_url.startswith("postgresql://")
    assert "synthetic-password" not in repr(settings)
    with pytest.raises(RuntimeError, match="SQLite path"):
        _ = settings.db_path


@pytest.mark.parametrize("value", ["sqlite:///file", "mysql://example.com/db", "postgresql://bad%xx/test"])
def test_unsupported_or_invalid_url_is_rejected_without_echo(monkeypatch, value):
    monkeypatch.setenv("OPENREPORTING_DATABASE_URL", value)
    with pytest.raises(ValueError) as exc:
        Settings.from_env()
    assert value not in str(exc.value)


def test_empty_url_preserves_sqlite(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENREPORTING_DATABASE_URL", raising=False)
    settings = replace(Settings.from_env(), data_dir=tmp_path)
    assert settings.db_path == tmp_path / "state.sqlite3"
