"""Report pipeline notifications: transactional outbox, recipient rules, retries, in-app view."""

from contextlib import contextmanager
from dataclasses import replace

import pytest

from openreporting import dashboards, security
from openreporting.config import Settings
from openreporting.db import connect, init_db, transaction
from openreporting.reporting import notifications, service

PASSWORD = "isolated-notify-password"


@pytest.fixture
def state(tmp_path):
    settings = replace(
        Settings.from_env(),
        data_dir=tmp_path / "data",
        database_url="",
        secret_key_file="",
        ldap_enabled=False,
        mail_enabled=False,
        zabbix_url="",
        zabbix_token_file="",
        smtp_host="",
        smtp_from="",
        smtp_user="",
        smtp_password="",
        recipient_domains=(),
    )
    init_db(settings)
    owner_id = security.create_user(settings, "reportowner", PASSWORD, "editor")
    with connect(settings) as db, transaction(db):
        db.execute("UPDATE users SET email='owner@example.com' WHERE id=?", (owner_id,))
    owner = {"id": owner_id, "role": "editor"}
    dashboards.save(settings, owner, {"uid": "notify", "title": "Notify", "panels": []})
    report = service.save_report(settings, owner, {"name": "Weekly ops", "dashboard_uid": "notify", "formats": ["csv"]})
    return settings, owner, report["id"]


def _events(settings):
    with connect(settings) as db:
        return [dict(r) for r in db.execute("SELECT event,status,attempts,run_id FROM notification_outbox ORDER BY id")]


def _fail_run(settings, owner, report_id, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("source exploded")

    monkeypatch.setattr(service, "build_outputs", broken)
    run_id = service.request_run(settings, owner, report_id, {})["run_id"]
    assert service.claim(settings) == run_id
    service.execute(settings, run_id)
    return run_id


def test_failed_run_is_queued_in_the_same_transaction_and_visible_in_app(state, monkeypatch):
    settings, owner, report_id = state
    run_id = _fail_run(settings, owner, report_id, monkeypatch)
    assert _events(settings) == [{"event": "run_failed", "status": "pending", "attempts": 0, "run_id": run_id}]
    visible = notifications.recent_for(settings, owner)
    assert visible[0]["report_name"] == "Weekly ops" and visible[0]["title"].startswith("Rapor çalışması başarısız")
    # Without mail nothing can be sent: the event is marked, not retried forever.
    notifications.deliver_pending(settings)
    assert _events(settings)[0]["status"] == "skipped"


def test_rolled_back_change_never_notifies(state):
    settings, _, report_id = state
    with pytest.raises(RuntimeError):
        with connect(settings) as db, transaction(db):
            notifications.notify(db, "run_failed", report_id)
            raise RuntimeError("rollback")
    assert _events(settings) == []


def test_unknown_event_is_rejected(state):
    settings, _, report_id = state
    with connect(settings) as db, transaction(db), pytest.raises(ValueError):
        notifications.notify(db, "anything", report_id)


class FakeSMTP:
    sent = []
    fail = 0

    def send_message(self, message, from_addr, to_addrs):
        if FakeSMTP.fail:
            FakeSMTP.fail -= 1
            raise OSError("relay down")
        FakeSMTP.sent.append((to_addrs[0], message["Subject"], message.get_content()))


@contextmanager
def fake_connection(settings):
    yield FakeSMTP()


def _mail(settings):
    return replace(settings, mail_enabled=True, smtp_host="smtp.example.com", smtp_from="ops@example.com", recipient_domains=("example.com",))


def test_delivery_goes_only_to_eligible_recipients_without_report_data(state, monkeypatch):
    settings, owner, report_id = state
    monkeypatch.setattr(notifications, "smtp_connection", fake_connection)
    FakeSMTP.sent, FakeSMTP.fail = [], 0
    _fail_run(settings, owner, report_id, monkeypatch)
    notifications.deliver_pending(_mail(settings))
    assert [to for to, _, _ in FakeSMTP.sent] == ["owner@example.com"]
    subject, body = FakeSMTP.sent[0][1], FakeSMTP.sent[0][2]
    assert "Weekly ops" in subject and "Profil" in body
    assert _events(settings)[0]["status"] == "sent"
    # Opted-out or outside the allowed domains: nobody is mailed and the event is skipped.
    with connect(settings) as db, transaction(db):
        db.execute(
            "INSERT INTO user_prefs(user_id,theme,timezone,notify_report_failures,updated_at) VALUES(?,?,?,?,?)",
            (owner["id"], "dark", "browser", 0, "2026-01-01T00:00:00+00:00"),
        )
        notifications.notify(db, "delivery_unknown", report_id)
    FakeSMTP.sent = []
    notifications.deliver_pending(_mail(settings))
    assert FakeSMTP.sent == [] and _events(settings)[-1]["status"] == "skipped"


def test_smtp_errors_are_retried_a_bounded_number_of_times(state, monkeypatch):
    settings, owner, report_id = state
    monkeypatch.setattr(notifications, "smtp_connection", fake_connection)
    FakeSMTP.sent, FakeSMTP.fail = [], 10
    with connect(settings) as db, transaction(db):
        notifications.notify(db, "run_failed", report_id)
    for expected in ("pending", "pending", "failed", "failed"):
        notifications.deliver_pending(_mail(settings))
        assert _events(settings)[0]["status"] == expected
    assert _events(settings)[0]["attempts"] == notifications.MAX_ATTEMPTS


def test_users_who_cannot_open_the_report_see_nothing(state):
    settings, owner, report_id = state
    admin = {"id": security.create_user(settings, "folderadmin", PASSWORD, "admin"), "role": "admin"}
    stranger = {"id": security.create_user(settings, "stranger", PASSWORD, "viewer"), "role": "viewer"}
    folder = dashboards.save_folder(settings, admin, "Restricted ops")
    dashboards.save(settings, admin, {"uid": "notify", "title": "Notify", "panels": []}, folder_uid=folder["uid"], overwrite=True)
    with connect(settings) as db, transaction(db):
        folder_id = db.execute("SELECT folder_id FROM dashboards WHERE uid='notify'").fetchone()["folder_id"]
        db.execute("INSERT INTO folder_policy(folder_id,restricted,revision) VALUES(?,1,1)", (folder_id,))
        notifications.notify(db, "run_failed", report_id)
    assert folder_id
    assert notifications.recent_for(settings, stranger) == []
    assert notifications.recent_for(settings, admin)


def test_editing_a_scheduled_report_notifies_that_schedules_were_disabled(state):
    settings, owner, report_id = state
    with connect(settings) as db, transaction(db):
        db.execute(
            """INSERT INTO dash_report_schedules(id,report_id,cadence,timezone,hour,minute,weekday,month_day,recipients_json,
               enabled,next_due,created_by,updated_at) VALUES('s1',?,'daily','UTC',8,0,0,1,'[]',1,'2030-01-01T00:00:00+00:00',?,'x')""",
            (report_id, owner["id"]),
        )
    service.save_report(settings, owner, {"name": "Weekly ops v2", "dashboard_uid": "notify", "formats": ["csv"]}, report_id=report_id)
    assert _events(settings)[-1]["event"] == "schedules_disabled_report_changed"
