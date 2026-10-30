"""The installer must not orphan existing credentials when its key file was lost."""
from dataclasses import replace

from cryptography.fernet import Fernet
import pytest

from openreporting.config import Settings
from openreporting.secrets_store import SecretError,installation_key_path


def test_fresh_install_can_prepare_default_key_without_creating_it(tmp_path):
    settings=replace(Settings.from_env(),data_dir=tmp_path,database_url='',secret_key_file='')
    path=installation_key_path(settings)
    assert path==tmp_path / 'secret.key' and not path.exists() and not settings.db_path.exists()


def test_existing_store_without_key_is_never_treated_as_fresh(tmp_path):
    settings=replace(Settings.from_env(),data_dir=tmp_path,database_url='',secret_key_file='')
    settings.db_path.touch()  # Even an empty/failed store needs deliberate recovery.
    with pytest.raises(SecretError,match='original encryption key'):installation_key_path(settings)
    assert not (tmp_path / 'secret.key').exists()


def test_custom_existing_key_is_validated_and_not_replaced(tmp_path):
    path=tmp_path / 'operator-key';original=Fernet.generate_key();path.write_bytes(original)
    settings=replace(Settings.from_env(),data_dir=tmp_path,database_url='',secret_key_file=str(path))
    assert installation_key_path(settings)==path and path.read_bytes()==original
    path.write_text('invalid-key')
    with pytest.raises(SecretError):installation_key_path(settings)
