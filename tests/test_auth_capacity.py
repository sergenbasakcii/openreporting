from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading
import sqlite3

from fastapi import HTTPException
from psycopg import OperationalError as PostgresUnavailable
import pytest

from openreporting import db, security
from openreporting.config import Settings


@pytest.fixture
def settings(tmp_path):
    settings = replace(
        Settings.from_env(), data_dir=tmp_path, database_url="", secret_key_file="", ldap_enabled=False, mail_enabled=False, zabbix_url="", zabbix_token_file=""
    )
    db.init_db(settings)
    security.create_user(settings, "admin1", "isolated-auth-capacity-password", "admin")
    return settings


def test_expensive_login_is_bounded_and_overflow_has_no_state_mutation(settings, monkeypatch):
    original = security.check_password
    release = threading.Event()
    all_entered = threading.Event()
    lock = threading.Lock()
    entered = 0

    def blocked_check(password, encoded):
        nonlocal entered
        with lock:
            entered += 1
            if entered == security.AUTH_CONCURRENCY:
                all_entered.set()
        assert release.wait(timeout=15)
        return original(password, encoded)

    monkeypatch.setattr(security, "check_password", blocked_check)
    with ThreadPoolExecutor(max_workers=security.AUTH_CONCURRENCY) as pool:
        futures = [pool.submit(security.login, settings, "admin1", "isolated-auth-capacity-password") for _ in range(security.AUTH_CONCURRENCY)]
        try:
            assert all_entered.wait(timeout=10)
            with db.connect(settings) as connection:
                before = connection.execute("SELECT count(*) FROM audit").fetchone()[0]
            with pytest.raises(HTTPException) as error:
                security.login(settings, "unknown-user", "not-a-password")
            assert error.value.status_code == 429 and error.value.headers["Retry-After"] == "1"
            assert entered == security.AUTH_CONCURRENCY
            with db.connect(settings) as connection:
                assert connection.execute("SELECT count(*) FROM audit").fetchone()[0] == before
                assert connection.execute("SELECT count(*) FROM login_failures").fetchone()[0] == 0
        finally:
            release.set()
        assert all(future.result()[0] for future in futures)
    assert security.login(settings, "admin1", "isolated-auth-capacity-password")[0]


@pytest.mark.parametrize("failure", [sqlite3.OperationalError, PostgresUnavailable, OSError])
def test_auth_admission_slots_are_released_on_backend_failure(settings, monkeypatch, failure):
    def unavailable(*args):
        raise failure("isolated-private-database-credential")

    with monkeypatch.context() as patch:
        patch.setattr(security, "_login", unavailable)
        for _ in range(security.AUTH_CONCURRENCY + 2):
            with pytest.raises(HTTPException) as error:
                security.login(settings, "admin1", "isolated-auth-capacity-password")
            assert error.value.status_code == 503
            assert "private" not in error.value.detail
    assert security.login(settings, "admin1", "isolated-auth-capacity-password")[0]
