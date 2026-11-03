"""Teams (user groups), team grants on folders and per-dashboard user/team permissions."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from openreporting import dashboard_access, dashboards, folder_access, security, teams
from openreporting.config import Settings
from openreporting.web import create_app

PASSWORD = "disposable-teams-test-password"


@pytest.fixture
def state(tmp_path):
    settings = replace(Settings.from_env(), data_dir=tmp_path, database_url="", secret_key_file="", secure_cookie=False, mfa_required_roles=())
    app = create_app(settings)
    users = {
        name: {"id": security.create_user(settings, name, PASSWORD, role), "role": role}
        for name, role in (("admin", "admin"), ("alice", "viewer"), ("bob", "viewer"), ("eve", "editor"))
    }
    folder = dashboards.save_folder(settings, users["admin"], "Network")
    for uid, folder_uid in (("noc", folder["uid"]), ("shared", None), ("finance", None)):
        dashboards.save(settings, users["admin"], {"uid": uid, "title": uid, "panels": []}, folder_uid=folder_uid)
    team = teams.create(settings, users["admin"]["id"], "NOC ekibi", "7/24 izleme")
    teams.set_members(settings, users["admin"]["id"], team["id"], [users["alice"]["id"], users["eve"]["id"]])
    return settings, app, users, folder["uid"], team["id"]


def signin(app, name):
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.post("/api/login", json={"username": name, "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return client


def visible(app, name):
    with signin(app, name) as client:
        return {r["uid"] for r in client.get("/api/search").json()}


def restrict_dashboard(settings, admin, uid, grants, restricted=True):
    revision = dashboard_access.policy(settings, admin, uid)["revision"]
    return dashboard_access.replace_policy(settings, admin, uid, {"restricted": restricted, "revision": revision, "grants": grants})


def test_team_grant_on_a_restricted_folder_reaches_every_member(state):
    settings, app, users, folder, team = state
    revision = folder_access.policy(settings, users["admin"], folder)["revision"]
    folder_access.replace_policy(
        settings, users["admin"], folder, {"restricted": True, "revision": revision, "grants": [], "team_grants": [{"team_id": team, "permission": "view"}]}
    )
    assert "noc" in visible(app, "alice") and "noc" not in visible(app, "bob")
    assert folder_access.policy(settings, users["admin"], folder)["team_grants"] == [{"team_id": team, "name": "NOC ekibi", "permission": "view"}]
    # Removing a member removes access immediately; the team itself grants nothing to others.
    teams.set_members(settings, users["admin"]["id"], team, [users["eve"]["id"]])
    assert "noc" not in visible(app, "alice")


def test_restricted_dashboard_is_visible_only_to_its_user_and_team_grants(state):
    settings, app, users, _, team = state
    restrict_dashboard(settings, users["admin"], "finance", [{"principal_type": "user", "principal_id": users["bob"]["id"], "permission": "view"}])
    assert "finance" in visible(app, "bob") and "finance" not in visible(app, "alice")
    with signin(app, "alice") as client:
        assert client.get("/api/dashboards/uid/finance").status_code == 404
    restrict_dashboard(settings, users["admin"], "finance", [{"principal_type": "team", "principal_id": team, "permission": "view"}])
    assert "finance" in visible(app, "alice") and "finance" not in visible(app, "bob")
    assert "shared" in visible(app, "bob")  # other dashboards keep folder rules


def test_dashboard_grant_can_share_one_dashboard_out_of_a_restricted_folder(state):
    settings, app, users, folder, _ = state
    revision = folder_access.policy(settings, users["admin"], folder)["revision"]
    folder_access.replace_policy(settings, users["admin"], folder, {"restricted": True, "revision": revision, "grants": []})
    assert "noc" not in visible(app, "bob")
    restrict_dashboard(settings, users["admin"], "noc", [{"principal_type": "user", "principal_id": users["bob"]["id"], "permission": "view"}])
    assert "noc" in visible(app, "bob")


def test_edit_needs_an_edit_grant_and_an_editor_role(state):
    settings, app, users, _, team = state
    restrict_dashboard(settings, users["admin"], "shared", [{"principal_type": "team", "principal_id": team, "permission": "view"}])
    with signin(app, "eve") as client:
        meta = client.get("/api/dashboards/uid/shared").json()["meta"]
        assert meta["canEdit"] is False
        model = client.get("/api/dashboards/uid/shared").json()["dashboard"]
        assert client.post("/api/dashboards/db", json={"dashboard": model, "overwrite": True}).status_code in (403, 404)
    restrict_dashboard(settings, users["admin"], "shared", [{"principal_type": "team", "principal_id": team, "permission": "edit"}])
    with signin(app, "eve") as client:
        assert client.get("/api/dashboards/uid/shared").json()["meta"]["canEdit"] is True
    with signin(app, "alice") as client:  # same team, but the viewer role caps it at read
        assert client.get("/api/dashboards/uid/shared").json()["meta"]["canEdit"] is False


def test_policies_are_admin_only_validated_and_optimistic(state):
    settings, app, users, _, team = state
    with signin(app, "eve") as client:
        assert client.get("/api/teams").status_code == 403
        assert client.put("/api/dashboards/uid/shared/permissions", json={"restricted": True, "revision": 0, "grants": []}).status_code == 403
    with signin(app, "admin") as client:
        bad = client.put(
            "/api/dashboards/uid/shared/permissions",
            json={"restricted": True, "revision": 0, "grants": [{"principal_type": "team", "principal_id": "nope", "permission": "view"}]},
        )
        assert bad.status_code == 422
        ok = client.put("/api/dashboards/uid/shared/permissions", json={"restricted": True, "revision": 0, "grants": []})
        assert ok.status_code == 200 and ok.json()["revision"] == 1
        stale = client.put("/api/dashboards/uid/shared/permissions", json={"restricted": False, "revision": 0, "grants": []})
        assert stale.status_code == 409
        assert client.post("/api/teams", json={"name": "noc EKİBİ"}).status_code in (201, 409)
        assert client.post("/api/teams", json={"name": "NOC ekibi"}).status_code == 409
        listed = client.get("/api/teams").json()
        assert listed[0]["name"] == "NOC ekibi" and {m["username"] for m in listed[0]["members"]} == {"alice", "eve"}


def test_deleting_a_team_removes_its_access(state):
    settings, app, users, _, team = state
    restrict_dashboard(settings, users["admin"], "finance", [{"principal_type": "team", "principal_id": team, "permission": "view"}])
    assert "finance" in visible(app, "alice")
    teams.delete(settings, users["admin"]["id"], team)
    assert "finance" not in visible(app, "alice")
    assert dashboard_access.policy(settings, users["admin"], "finance")["grants"] == []
