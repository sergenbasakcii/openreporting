"""Theme preferences: curated ids are stored, legacy dark/light still read, anything else is rejected."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from openreporting import security, themes
from openreporting.config import Settings
from openreporting.db import connect, transaction
from openreporting.web import create_app

PASSWORD = "isolated-theme-password"


@pytest.fixture
def client(tmp_path):
    settings = replace(Settings.from_env(), data_dir=tmp_path / "data", database_url="", secret_key_file="", secure_cookie=True, mfa_required_roles=())
    app = create_app(settings)
    uid = security.create_user(settings, "themeuser", PASSWORD, "viewer")
    http = TestClient(app, base_url="https://localhost")
    signed = http.post("/api/login", json={"username": "themeuser", "password": PASSWORD})
    assert signed.status_code == 200
    http.headers["X-CSRF-Token"] = signed.json()["csrf"]
    return http, settings, uid


def _save(http, theme):
    return http.put("/api/user/preferences", json={"theme": theme, "timezone": "browser"})


def test_new_users_follow_the_system_theme(client):
    http, _, _ = client
    assert http.get("/api/user").json()["preferences"]["theme"] == themes.SYSTEM


@pytest.mark.parametrize("theme", [*themes.THEME_IDS, themes.SYSTEM])
def test_every_curated_theme_round_trips(client, theme):
    http, _, _ = client
    saved = _save(http, theme)
    assert saved.status_code == 200, saved.text
    assert saved.json()["theme"] == theme
    assert http.get("/api/user").json()["preferences"]["theme"] == theme


def test_legacy_values_are_migrated_on_save_and_on_read(client):
    http, settings, uid = client
    assert _save(http, "light").json()["theme"] == "porcelain"
    with connect(settings) as db, transaction(db):
        db.execute("UPDATE user_prefs SET theme='dark' WHERE user_id=?", (uid,))
    assert http.get("/api/user").json()["preferences"]["theme"] == "aurora"


@pytest.mark.parametrize("theme", ["", "neon", "AURORA", "<script>", "x" * 300])
def test_unknown_themes_are_rejected(client, theme):
    http, _, _ = client
    assert _save(http, theme).status_code == 422
