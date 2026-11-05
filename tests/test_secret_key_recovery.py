"""A missing key must never be replaced when credential state is unknown."""

from dataclasses import replace

import pytest

from openreporting.config import Settings
from openreporting.db import connect, has_encrypted_secrets, init_db
from openreporting.secrets_store import SecretError, decrypt, encrypt, key_path, reset_cache


@pytest.fixture
def settings(tmp_path):
    reset_cache()
    yield replace(Settings.from_env(), data_dir=tmp_path / "data", secret_key_file="")
    reset_cache()


def test_new_install_generates_key_without_creating_database(settings):
    token = encrypt(settings, {"token": "test-value"})
    assert decrypt(settings, token) == {"token": "test-value"}
    assert key_path(settings).is_file()
    assert not settings.db_path.exists()


def test_initialised_empty_database_allows_key_creation(settings):
    init_db(settings)
    assert not has_encrypted_secrets(settings)
    token = encrypt(settings, {"token": "test-value"})
    assert decrypt(settings, token) == {"token": "test-value"}


def test_missing_key_with_stored_credentials_is_not_replaced(settings):
    init_db(settings)
    token = encrypt(settings, {"token": "test-value"})
    with connect(settings) as db:
        db.execute(
            """INSERT INTO datasources
            (id,uid,name,type,secure_json,created_at,updated_at,updated_by)
            VALUES (?,?,?,?,?,?,?,?)""",
            ("test", "test", "Test", "testdata", token, "test", "test", "test"),
        )
    key_path(settings).unlink()
    reset_cache()
    assert has_encrypted_secrets(settings)
    with pytest.raises(SecretError, match="anahtarı yedekten"):
        encrypt(settings, {"token": "replacement"})
    assert not key_path(settings).exists()


def test_unreadable_database_does_not_authorise_key_generation(settings):
    settings.data_dir.mkdir(parents=True)
    contents = b"invalid database; credential state is unknown"
    settings.db_path.write_bytes(contents)
    with pytest.raises(SecretError, match="yeni anahtar oluşturulmadı"):
        encrypt(settings, {"token": "test-value"})
    assert not key_path(settings).exists()
    assert settings.db_path.read_bytes() == contents


def test_existing_database_with_unknown_schema_does_not_authorise_key_generation(settings):
    settings.data_dir.mkdir(parents=True)
    settings.db_path.touch()
    with pytest.raises(SecretError, match="yeni anahtar oluşturulmadı"):
        encrypt(settings, {"token": "test-value"})
    assert not key_path(settings).exists()


def test_read_only_inspection_handles_special_characters_in_path(settings):
    settings = replace(settings, data_dir=settings.data_dir / "space # question ? unicode ç")
    # '?' is not a valid Windows filename; exercise the other URI-sensitive characters there.
    import os

    if os.name == "nt":
        settings = replace(settings, data_dir=settings.data_dir.with_name("space # unicode ç"))
    init_db(settings)
    assert not has_encrypted_secrets(settings)


def test_ensure_key_creates_key_once_for_the_installer(settings):
    from openreporting.secrets_store import ensure_key

    init_db(settings)
    path = ensure_key(settings)
    first = path.read_bytes()
    reset_cache()
    assert ensure_key(settings) == path and path.read_bytes() == first
    assert decrypt(settings, encrypt(settings, {"token": "test-value"})) == {"token": "test-value"}
