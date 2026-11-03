"""Plugin system: allow-listed datasource entry points and same-origin panel modules."""

import shutil
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openreporting import datasources, plugins, security
from openreporting.config import Settings
from openreporting.datasources.base import DataSourceError
from openreporting.web import create_app

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "isolated-plugin-password"


class FakeEntryPoint:
    def __init__(self, name, target):
        self.name, self._target = name, target
        self.dist = type("Dist", (), {"version": "1.0.0"})()

    def load(self):
        if isinstance(self._target, Exception):
            raise self._target
        return self._target


@pytest.fixture
def example_class(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "examples" / "datasource-plugin"))
    sys.modules.pop("openreporting_plugin_static", None)
    import openreporting_plugin_static

    yield openreporting_plugin_static.StaticTableDataSource
    for registry in (datasources.TYPES, datasources.SECURE_FIELDS):
        registry.pop("x-static-table", None)
    datasources.TYPE_INFO[:] = [t for t in datasources.TYPE_INFO if t["type"] != "x-static-table"]
    plugins._status.clear()


@pytest.fixture
def settings(tmp_path):
    from openreporting.db import init_db

    value = replace(Settings.from_env(), data_dir=tmp_path / "data", database_url="", secret_key_file="", mfa_required_roles=())
    init_db(value)
    return value


def test_allow_listed_datasource_plugin_registers_validates_and_queries(settings, example_class, monkeypatch):
    monkeypatch.setenv("OPENREPORTING_PLUGINS", "x-static-table")
    plugins.load_datasource_plugins([FakeEntryPoint("x-static-table", example_class)])
    assert datasources.TYPES["x-static-table"] is example_class
    assert any(t["type"] == "x-static-table" and t.get("plugin") for t in datasources.TYPE_INFO)
    with pytest.raises(DataSourceError, match="rows"):
        datasources.save(settings, "tester", {"type": "x-static-table", "name": "Bad", "jsonData": {"columns": ["a"], "rows": [[1, 2]]}})
    uid = datasources.save(
        settings, "tester", {"type": "x-static-table", "name": "Inventory", "jsonData": {"columns": ["host", "cpu"], "rows": [["web-1", 12.5]]}}
    )
    source = datasources.get(settings, uid)
    frames = source.query({"refId": "A"}, None).frames
    assert frames[0]["rows"] == [["web-1", 12.5]] and source.health()["status"] == "ok"


def test_plugins_load_only_when_allow_listed_and_broken_ones_never_break_startup(example_class, monkeypatch):
    monkeypatch.setenv("OPENREPORTING_PLUGINS", "x-broken,x-mismatch")
    plugins.load_datasource_plugins(
        [
            FakeEntryPoint("x-static-table", example_class),  # installed but not allow-listed
            FakeEntryPoint("x-broken", ImportError("missing dependency")),
            FakeEntryPoint("x-mismatch", example_class),  # type attribute differs from the entry point name
            FakeEntryPoint("not-prefixed", example_class),  # can never shadow built-in types
        ]
    )
    states = {s["id"]: s["state"] for s in plugins._status.values()}
    assert states == {"x-static-table": "disabled", "x-broken": "error", "x-mismatch": "error"}
    assert "x-static-table" not in datasources.TYPES and "not-prefixed" not in datasources.TYPES


def test_unknown_datasource_types_are_still_rejected(settings):
    with pytest.raises(DataSourceError):
        datasources.save(settings, "tester", {"type": "x-not-installed", "name": "Ghost"})


@pytest.fixture
def panel_app(tmp_path, monkeypatch):
    plugin_root = tmp_path / "plugins"
    shutil.copytree(ROOT / "plugins" / "examples" / "x-bullet", plugin_root / "x-bullet")
    (plugin_root / "x-bullet" / "secret.txt").write_text("not servable")
    broken = plugin_root / "x-wrong-id"
    broken.mkdir()
    (broken / "plugin.json").write_text('{"id": "x-other", "type": "panel", "module": "module.js"}')
    monkeypatch.setenv("OPENREPORTING_PLUGIN_DIR", str(plugin_root))
    monkeypatch.setenv("OPENREPORTING_PLUGINS", "x-bullet,x-wrong-id")
    settings = replace(Settings.from_env(), data_dir=tmp_path / "data", database_url="", secret_key_file="", secure_cookie=True, mfa_required_roles=())
    app = create_app(settings)
    security.create_user(settings, "pluginadmin", PASSWORD, "admin")
    client = TestClient(app, base_url="https://localhost")
    signed = client.post("/api/login", json={"username": "pluginadmin", "password": PASSWORD})
    assert signed.status_code == 200
    yield app, client
    plugins._status.clear()


def test_panel_plugins_are_listed_and_served_same_origin_only_when_enabled(panel_app, monkeypatch):
    app, client = panel_app
    listed = client.get("/api/plugins").json()
    assert [p["id"] for p in listed] == ["x-bullet"] and listed[0]["style_url"] == "/plugins/x-bullet/style.css"
    module = client.get("/plugins/x-bullet/module.js")
    assert module.status_code == 200 and module.headers["content-type"].startswith("text/javascript")
    assert "registerPanel('x-bullet'" in module.text
    assert client.get("/plugins/x-bullet/secret.txt").status_code == 404  # extension not servable
    assert client.get("/plugins/x-bullet/..%2F..%2Fdata%2Fstate.sqlite3").status_code == 404
    status = {s["id"]: s for s in client.get("/api/admin/plugins").json()["plugins"]}
    assert status["x-bullet"]["state"] == "loaded" and status["x-wrong-id"]["state"] == "error"
    monkeypatch.setenv("OPENREPORTING_PLUGINS", "")
    assert client.get("/api/plugins").json() == [] and client.get("/plugins/x-bullet/module.js").status_code == 404
    with TestClient(app, base_url="https://localhost") as anonymous:
        assert anonymous.get("/plugins/x-bullet/module.js").status_code == 401


def test_saved_dashboards_keep_plugin_panel_types_even_when_the_plugin_is_off(settings):
    from openreporting import dashboards, security

    user = {"id": security.create_user(settings, "paneleditor", PASSWORD, "editor"), "role": "editor"}
    saved = dashboards.save(settings, user, {"title": "Plugins", "panels": [{"id": 1, "type": "x-bullet", "title": "SLA"}, {"id": 2, "type": "fancy-unknown"}]})
    panels = dashboards.get(settings, saved["uid"], user)["dashboard"]["panels"]
    assert panels[0]["type"] == "x-bullet"  # preserved for when the plugin is enabled again
    assert panels[1]["type"] == "text"  # non-plugin unknown types are still neutralised
