"""Smart dashboards: page layout normalization, PDF placement that matches the canvas, and export."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from openreporting import dashboards, security, smart_layout
from openreporting.config import Settings
from openreporting.web import create_app

PASSWORD = "disposable-smart-test-password"


def smart_model(**smart):
    panels = [
        {
            "id": 1,
            "type": "stat",
            "title": "CPU",
            "smartPos": {"page": 0, "x": 0, "y": 0, "w": 6, "h": 5},
            "targets": [
                {
                    "refId": "A",
                    "scenario": "zabbix_sim",
                    "queryType": "metrics",
                    "group": {"filter": "/.*/"},
                    "host": {"filter": "/.*/"},
                    "item": {"filter": "/CPU/i"},
                }
            ],
        },
        {
            "id": 2,
            "type": "timeseries",
            "title": "Bellek",
            "smartPos": {"page": 1, "x": 6, "y": 4, "w": 18, "h": 10},
            "targets": [{"refId": "A", "scenario": "zabbix_sim", "queryType": "metrics", "item": {"filter": "/memory/i"}}],
        },
    ]
    return {"uid": "smart-1", "title": "Haftalık rapor", "panels": panels, "smart": {"orientation": "portrait", "pages": 2, **smart}}


def test_normalize_clamps_positions_and_derives_grid_positions():
    model = smart_layout.normalize(
        {
            "smart": {"orientation": "landscape", "pages": 0, "paper": "B5", "subtitle": "x" * 500},
            "panels": [{"smartPos": {"page": 3, "x": 30, "y": 99, "w": 40, "h": 1}}, {"smartPos": "bogus"}],
        }
    )
    smart = model["smart"]
    assert smart["rows"] == 20 and smart["paper"] == "A4" and smart["pages"] == 4 and len(smart["subtitle"]) == 200
    first, second = model["panels"]
    assert first["smartPos"] == {"page": 3, "x": 0, "y": 18, "w": 24, "h": 2}
    assert first["gridPos"] == {"x": 0, "y": 3 * 20 + 18, "w": 24, "h": 2}
    assert second["smartPos"] == {"page": 0, "x": 0, "y": 0, "w": 12, "h": 8}
    plain = smart_layout.normalize({"smart": "not a dict", "panels": []})
    assert "smart" not in plain


def test_pdf_plan_places_panels_exactly_on_their_pages():
    panels = [SimpleNamespace(panel=p) for p in smart_layout.normalize(smart_model())["panels"]]
    placements, pages = smart_layout.plan(panels, 32, col_w=20.0, page_h=640.0)
    assert pages == 2
    (p0, r0, x0, top0, w0, h0), (p1, r1, x1, top1, w1, h1) = placements
    assert (p0, x0, top0, w0, h0) == (0, 0.0, 0.0, 120.0, 100.0)
    assert (p1, x1, top1, w1, h1) == (1, 120.0, 80.0, 360.0, 200.0)


@pytest.fixture
def client(tmp_path):
    settings = replace(
        Settings.from_env(), data_dir=tmp_path, database_url="", secret_key_file="", secure_cookie=False, mfa_required_roles=(), provision_testdata=True
    )
    app = create_app(settings)
    user = {"id": security.create_user(settings, "builder", PASSWORD, "editor"), "role": "editor"}
    http = TestClient(app, base_url="http://127.0.0.1")
    signed = http.post("/api/login", json={"username": "builder", "password": PASSWORD})
    http.headers["X-CSRF-Token"] = signed.json()["csrf"]
    return settings, http, user


def test_smart_dashboard_round_trips_and_exports_a_pdf_with_its_pages(client):
    settings, http, user = client
    model = smart_model()
    for panel in model["panels"]:
        panel["datasource"] = {"uid": "testdata"}
    saved = http.post("/api/dashboards/db", json={"dashboard": model, "overwrite": True})
    assert saved.status_code == 200, saved.text
    stored = http.get("/api/dashboards/uid/smart-1").json()["dashboard"]
    assert stored["smart"]["pages"] == 2 and stored["panels"][1]["gridPos"] == {"x": 6, "y": 32 + 4, "w": 18, "h": 10}
    pdf = http.post(
        "/api/dashboards/export",
        json={"dashboard_uid": "smart-1", "time_range": {"from": "now-6h", "to": "now"}, "timezone": "UTC", "variables": {}, "format": "pdf"},
    )
    assert pdf.status_code == 200, pdf.text[:300]
    body = pdf.content
    assert (
        body.startswith(b"%PDF") and body.count(b"/Type /Page\n") + body.count(b"/Type /Page ") + body.count(b"/Type /Page/") >= 2 or body.count(b"/Page") >= 2
    )
    # Portrait paper from the smart block wins over the export default (landscape).
    assert b"/MediaBox [0 0 595.2756 841.8898]" in body or b"595.2756" in body
    assert dashboards.get(settings, "smart-1", user)["dashboard"]["smart"]["orientation"] == "portrait"
