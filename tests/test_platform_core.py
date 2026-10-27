"""Core platform behaviour: login hardening, scheduling maths, single worker, schema upgrades."""
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from openreporting.config import Settings
from openreporting.db import CURRENT_VERSION, audit, connect, init_db, transaction, verify_audit
from openreporting.security import create_user
from openreporting.web import create_app
from openreporting.worker import completed_period, exclusive_worker, run_forever, schedule_next, update_worker_heartbeat


@pytest.fixture
def settings(tmp_path):
    return replace(Settings.from_env(), data_dir=tmp_path, secure_cookie=False, mail_enabled=False,
                   zabbix_url="", zabbix_token_file="", provision_testdata=True)


@pytest.fixture
def http(settings):
    app = create_app(settings)
    create_user(settings, "admin1", "an-administrator-password", "admin")
    create_user(settings, "editor1", "an-editor-password-123", "editor")
    with TestClient(app) as client:
        yield client


def login(http, name, password):
    res = http.post("/api/login", json={"username": name, "password": password})
    assert res.status_code == 200, res.text
    return {"X-CSRF-Token": res.json()["csrf"]}


def test_failed_logins_are_persisted(http, settings):
    assert http.post("/api/login", json={"username": "editor1", "password": "wrong"}).status_code == 401
    with connect(settings) as db:
        assert db.execute("SELECT count FROM login_failures WHERE username='editor1'").fetchone()["count"] == 1


def test_mutations_require_csrf_and_audit_is_admin_only(http):
    headers = login(http, "editor1", "an-editor-password-123")
    assert http.post("/api/dashboards/db", json={"dashboard": {"title": "x"}}).status_code == 403
    assert http.post("/api/dashboards/db", headers=headers, json={"dashboard": {"title": "x"}}).status_code == 200
    assert http.get("/api/audit").status_code == 403
    http.post("/api/logout", headers=headers)
    login(http, "admin1", "an-administrator-password")
    entries = http.get("/api/audit")
    assert entries.status_code == 200 and entries.json()


def test_unknown_api_paths_are_404(http):
    login(http, "admin1", "an-administrator-password")
    for path in ("/api/does-not-exist", "/api/v2/anything"):
        assert http.get(path).status_code == 404, path


def test_only_known_roles_are_accepted(settings):
    init_db(settings)
    with pytest.raises(ValueError):
        create_user(settings, "superuser1", "a-superuser-password-12", "superuser")


def test_completed_calendar_month():
    start, end = completed_period("monthly", "Europe/Istanbul", "2026-04-01T06:00:00+00:00")
    assert (start, end) == ("2026-02-28T21:00:00+00:00", "2026-03-31T21:00:00+00:00")


def test_next_schedule_is_in_future():
    ref = datetime(2026, 10, 23, 10, tzinfo=timezone.utc)
    for cadence in ("daily", "weekly", "monthly", "yearly"):
        assert datetime.fromisoformat(schedule_next(cadence, "Europe/Istanbul", 9, 0, ref)) > ref


def test_single_worker_lock_heartbeat_and_one_cycle(settings):
    init_db(settings)
    with exclusive_worker(settings):
        with pytest.raises(RuntimeError, match="already active"):
            with exclusive_worker(settings):
                pass
        update_worker_heartbeat(settings, "worker-test", "2026-10-23T10:00:00+00:00")
    with connect(settings) as db:
        assert db.execute("SELECT worker_id FROM worker_runtime").fetchone()[0] == "worker-test"
    run_forever(settings, once=True)  # one full cycle of the report worker must not raise
    with connect(settings) as db:
        row = db.execute("SELECT worker_id, last_error FROM worker_runtime").fetchone()
    assert row["worker_id"] != "worker-test" and row["last_error"] == ""


def test_fresh_schema_and_newer_schema_refused(settings):
    init_db(settings)
    init_db(settings)  # idempotent
    with connect(settings) as db, transaction(db):
        audit(db, "test", "schema.check", "db", "state")
    with connect(settings) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == CURRENT_VERSION
        assert verify_audit(db) == (True, None)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    with sqlite3.connect(settings.db_path) as db:
        db.execute(f"PRAGMA user_version={CURRENT_VERSION + 1}")
    with pytest.raises(RuntimeError, match="newer database schema"):
        init_db(settings)
