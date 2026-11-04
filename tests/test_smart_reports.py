"""Smart dashboard reporting: layout elements, per-panel periods, report-wide filters and per-host PDFs."""

import base64
import re
import io
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from openreporting import dashboards, security
from openreporting.config import Settings
from openreporting.domain import DomainError
from openreporting.reporting.collect import _panel_range
from openreporting.web import create_app

PASSWORD = "disposable-smart-report-password"
DS = {"uid": "testdata", "type": "testdata"}


def target(item, **extra):
    return {
        "refId": "A",
        "scenario": "zabbix_sim",
        "queryType": "metrics",
        "group": {"filter": "$group"},
        "host": {"filter": "$host"},
        "item": {"filter": item},
        **extra,
    }


def model(logo_id=None, filters=True):
    variables = [
        {
            "name": "group",
            "label": "Grup",
            "type": "query",
            "datasource": DS,
            "query": {"type": "group", "group": "/.*/"},
            "includeAll": True,
            "current": {"value": "$__all"},
        },
        {
            "name": "host",
            "label": "Host",
            "type": "query",
            "datasource": DS,
            "query": {"type": "host", "group": "$group", "host": "/.*/"},
            "multi": True,
            "includeAll": True,
            "current": {"value": ["$__all"]},
        },
    ]
    return {
        "uid": "smart-report",
        "title": "Akıllı rapor",
        "tags": ["akıllı"],
        "templating": {"list": variables if filters else []},
        "smart": {"orientation": "portrait", "pages": 1, "logo_id": logo_id, "footer": "ACME · gizli", "filters": filters},
        "panels": [
            {"id": 1, "type": "image", "title": "Logo", "options": {}, "smartPos": {"page": 0, "x": 0, "y": 0, "w": 6, "h": 3}},
            {"id": 2, "type": "divider", "title": "$host özeti", "options": {"style": "brand"}, "smartPos": {"page": 0, "x": 6, "y": 0, "w": 18, "h": 3}},
            {"id": 3, "type": "reportinfo", "options": {"showVariables": True}, "smartPos": {"page": 0, "x": 0, "y": 3, "w": 24, "h": 4}},
            {
                "id": 4,
                "type": "stat",
                "title": "CPU",
                "datasource": DS,
                "targets": [target("/CPU utilization/i", functions=[{"name": "averageSeries", "params": []}])],
                "smartPos": {"page": 0, "x": 0, "y": 7, "w": 12, "h": 6},
            },
            {
                "id": 5,
                "type": "timeseries",
                "title": "Trafik · son 1 yıl",
                "datasource": DS,
                "timeRange": {"from": "now-1y", "to": "now"},
                "targets": [target("/Bits/i")],
                "smartPos": {"page": 0, "x": 0, "y": 13, "w": 24, "h": 10},
            },
        ],
    }


@pytest.fixture
def env(tmp_path):
    settings = replace(
        Settings.from_env(), data_dir=tmp_path, database_url="", secret_key_file="", secure_cookie=False, mfa_required_roles=(), provision_testdata=True
    )
    app = create_app(settings)
    user = {"id": security.create_user(settings, "smartuser", PASSWORD, "editor"), "role": "editor"}
    http = TestClient(app, base_url="http://127.0.0.1")
    http.headers["X-CSRF-Token"] = http.post("/api/login", json={"username": "smartuser", "password": PASSWORD}).json()["csrf"]
    return settings, http, user


def upload_logo(http):
    buffer = io.BytesIO()
    Image.new("RGB", (120, 40), (79, 70, 229)).save(buffer, format="PNG")
    res = http.post("/api/dash-reports/logos", json={"data": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def pdf_reader():
    # Text extraction needs pypdfium2 (developer tool, not a runtime dependency); page structure is
    # still asserted without it.
    return pytest.importorskip("pypdfium2")


def page_count(data):
    return len(re.findall(rb"/Type /Page[^s]", data))


def export_bytes(http, **extra):
    body = {"dashboard_uid": "smart-report", "time_range": {"from": "now-24h", "to": "now"}, "timezone": "UTC", "variables": {}, "format": "pdf", **extra}
    res = http.post("/api/dashboards/export", json=body)
    assert res.status_code == 200, res.text[:300]
    return res.content


def export(http, **extra):
    return pdf_reader().PdfDocument(export_bytes(http, **extra))


def page_text(pdf, index):
    return pdf[index].get_textpage().get_text_range()


def test_layout_elements_logo_footer_and_panel_period_reach_the_pdf(env):
    settings, http, user = env
    logo = upload_logo(http)
    assert http.post("/api/dashboards/db", json={"dashboard": model(logo_id=logo), "overwrite": True}).status_code == 200
    stored = dashboards.get(settings, "smart-report", user)["dashboard"]
    assert stored["smart"]["logo_id"] == logo and stored["panels"][4]["timeRange"] == {"from": "now-1y", "to": "now"}
    pdf = export(http)
    assert len(pdf) == 1
    text = page_text(pdf, 0)
    assert "ACME · gizli" in text  # smart footer replaces the default footer
    assert "Rapor dönemi" in text and "Trafik · son 1 yıl" in text
    year = datetime.now(timezone.utc).year
    assert f"{year - 1}" in text and "Görsel bulunamadı" not in text  # own period printed; empty image used the logo
    assert pdf[0].get_size()[0] < pdf[0].get_size()[1]  # portrait


def test_per_host_export_gives_each_host_its_own_pages_and_selection(env):
    _, http, _ = env
    assert http.post("/api/dashboards/db", json={"dashboard": model(), "overwrite": True}).status_code == 200
    pdf = export(http, split_by="host")
    assert len(pdf) > 3
    first, second = page_text(pdf, 0), page_text(pdf, 1)
    host_line = next(line for line in first.splitlines() if line.startswith("Host:"))
    assert host_line != next(line for line in second.splitlines() if line.startswith("Host:"))
    # The report info card shows the section's own host, not the report-wide "Tümü".
    assert host_line.split(":", 1)[1].strip() in first.split("Rapor dönemi", 1)[1]


def test_panel_periods_are_validated_and_anchored_at_the_report_end():
    with pytest.raises(DomainError):
        dashboards.normalize({"title": "x", "panels": [{"type": "stat", "timeRange": {"from": "yesterday-ish", "to": "now"}}]})
    with pytest.raises(DomainError):
        dashboards.normalize({"title": "x", "panels": [{"type": "stat", "timeRange": {"from": "now", "to": "now-1d"}}]})
    clean = dashboards.normalize({"title": "x", "panels": [{"type": "stat", "timeRange": {}}]})
    assert "timeRange" not in clean["panels"][0]
    end = datetime(2026, 3, 1, tzinfo=timezone.utc)
    rng = {"from": str(int(end.timestamp() * 1000) - 86400000), "to": str(int(end.timestamp() * 1000))}
    own = _panel_range({"timeRange": {"from": "now-1y", "to": "now"}}, rng, "UTC")
    assert int(own["to"]) == int(rng["to"]) and datetime.fromtimestamp(int(own["from"]) / 1000, timezone.utc).date().isoformat() == "2025-03-01"
    fixed = _panel_range({"timeRange": {"from": "2025-01-01 00:00:00", "to": "2025-12-31 23:59:59"}}, rng, "UTC")
    assert datetime.fromtimestamp(int(fixed["from"]) / 1000, timezone.utc).date().isoformat() == "2025-01-01"


def test_smart_block_rejects_bad_logo_ids_and_keeps_branding_fields():
    out = dashboards.normalize({"title": "x", "smart": {"logo_id": "../../etc/passwd", "footer": "f" * 400, "filters": 1}, "panels": []})
    assert out["smart"]["logo_id"] is None and len(out["smart"]["footer"]) == 160 and out["smart"]["filters"] is True


def test_smart_pdf_structure_without_a_pdf_reader(env):
    _, http, _ = env
    assert http.post("/api/dashboards/db", json={"dashboard": model(), "overwrite": True}).status_code == 200
    single = export_bytes(http)
    assert single.startswith(b"%PDF") and page_count(single) == 1
    assert page_count(export_bytes(http, split_by="host")) > 3
