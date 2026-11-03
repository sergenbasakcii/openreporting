"""Service-account API tokens: issuance, bearer auth, scope limits, expiry/revocation and folder ACLs."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from openreporting import dashboards, security
from openreporting.config import Settings
from openreporting.db import connect, transaction
from openreporting.web import create_app

PASSWORD = "isolated-token-admin-password"


@pytest.fixture
def state(tmp_path):
    settings = replace(
        Settings.from_env(),
        data_dir=tmp_path / "data",
        database_url="",
        secret_key_file="",
        secure_cookie=True,
        ldap_enabled=False,
        mail_enabled=False,
        mfa_required_roles=(),
        zabbix_url="",
        zabbix_token_file="",
    )
    app = create_app(settings)
    admin_id = security.create_user(settings, "tokenadmin", PASSWORD, "admin")
    return settings, app, admin_id


def admin_client(app):
    client = TestClient(app, base_url="https://localhost")
    signed = client.post("/api/login", json={"username": "tokenadmin", "password": PASSWORD})
    assert signed.status_code == 200, signed.text
    client.headers["X-CSRF-Token"] = signed.json()["csrf"]
    return client


def make_token(client, role="viewer", username="svc-ci"):
    account = client.post("/api/admin/service-accounts", json={"username": username, "role": role})
    assert account.status_code == 201, account.text
    issued = client.post(f"/api/admin/service-accounts/{account.json()['id']}/tokens", json={"name": "CI", "days": 30, "password": PASSWORD})
    assert issued.status_code == 201, issued.text
    return account.json()["id"], issued.json()


def bearer(app, token):
    return TestClient(app, base_url="https://localhost", headers={"Authorization": f"Bearer {token}"})


def test_token_is_shown_once_stored_hashed_and_works_without_csrf(state):
    settings, app, _ = state
    with admin_client(app) as client:
        account_id, issued = make_token(client, role="editor")
        listed = client.get("/api/admin/service-accounts").json()
    assert issued["token"].startswith("ortk_") and issued["token"] not in str(listed)
    with connect(settings) as db:
        stored = db.execute("SELECT token_hash FROM api_tokens").fetchone()["token_hash"]
    assert issued["token"] not in stored and len(stored) == 64
    with bearer(app, issued["token"]) as api:
        assert api.get("/api/search").status_code == 200
        saved = api.post("/api/dashboards/db", json={"dashboard": {"title": "From CI"}})  # editor mutation, no CSRF header
        assert saved.status_code == 200, saved.text
    with connect(settings) as db:
        assert db.execute("SELECT created_by FROM dashboards WHERE title='From CI'").fetchone()[0] == account_id


def test_viewer_token_cannot_write_and_tokens_never_reach_account_or_admin_endpoints(state):
    settings, app, _ = state
    with admin_client(app) as client:
        _, issued = make_token(client)
    with bearer(app, issued["token"]) as api:
        assert api.post("/api/dashboards/db", json={"dashboard": {"title": "Nope"}}).status_code == 403
        for path in ("/api/user", "/api/user/mfa", "/api/admin/settings", "/api/users", "/api/audit", "/api/session"):
            assert api.get(path).status_code == 403, path
        assert api.get("/api/openapi.json").json()["info"]["title"] == "OpenReporting API"


@pytest.mark.parametrize("mutate", ["revoke", "expire", "deactivate"])
def test_revoked_expired_or_disabled_tokens_are_rejected(state, mutate):
    settings, app, _ = state
    with admin_client(app) as client:
        account_id, issued = make_token(client)
        if mutate == "revoke":
            assert client.delete(f"/api/admin/tokens/{issued['id']}").status_code == 200
        elif mutate == "deactivate":
            assert client.patch(f"/api/admin/service-accounts/{account_id}", json={"active": False}).status_code == 200
    if mutate == "expire":
        with connect(settings) as db, transaction(db):
            db.execute("UPDATE api_tokens SET expires_at='2000-01-01T00:00:00+00:00'")
    with bearer(app, issued["token"]) as api:
        assert api.get("/api/search").status_code == 401


def test_malformed_and_unknown_tokens_and_missing_auth_are_rejected(state):
    settings, app, _ = state
    with bearer(app, "not-a-token") as api:
        assert api.get("/api/search").status_code == 401
    with bearer(app, "ortk_abcdefgh_" + "x" * 43) as api:
        assert api.get("/api/search").status_code == 401
    with TestClient(app, base_url="https://localhost") as anonymous:
        assert anonymous.get("/api/openapi.json").status_code == 401


def test_service_accounts_cannot_sign_in_become_admin_or_get_a_password(state):
    settings, app, _ = state
    with admin_client(app) as client:
        assert client.post("/api/admin/service-accounts", json={"username": "svc-root", "role": "admin"}).status_code == 422
        account_id, _ = make_token(client)
        assert client.patch(f"/api/users/{account_id}", json={"role": "admin"}).status_code == 409
        assert client.post(f"/api/users/{account_id}/password", json={"password": "a-brand-new-password-1"}).status_code == 409
        bad = client.post(f"/api/admin/service-accounts/{account_id}/tokens", json={"name": "x2", "days": 30, "password": "wrong-password-value"})
        assert bad.status_code == 403  # issuing requires the admin's password
    with TestClient(app, base_url="https://localhost") as anonymous:
        assert anonymous.post("/api/login", json={"username": "svc-ci", "password": "!service"}).status_code == 401


def test_folder_acl_applies_to_tokens_like_people(state):
    settings, app, admin_id = state
    admin = {"id": admin_id, "role": "admin"}
    folder = dashboards.save_folder(settings, admin, "Restricted")
    dashboards.save(settings, admin, {"uid": "secret-dash", "title": "Secret"}, folder_uid=folder["uid"])
    with connect(settings) as db, transaction(db):
        folder_id = db.execute("SELECT folder_id FROM dashboards WHERE uid='secret-dash'").fetchone()["folder_id"]
        db.execute("INSERT INTO folder_policy(folder_id,restricted,revision) VALUES(?,1,1)", (folder_id,))
    with admin_client(app) as client:
        _, issued = make_token(client)
    with bearer(app, issued["token"]) as api:
        assert api.get("/api/dashboards/uid/secret-dash").status_code in (403, 404)
        assert all(d.get("uid") != "secret-dash" for d in api.get("/api/search").json())
