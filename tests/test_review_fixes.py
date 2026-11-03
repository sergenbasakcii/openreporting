"""Regression tests for the security/backend review fixes (viewer isolation, SQL guard, report output safety)."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from openreporting import query_engine, templating
from openreporting.api.reports import content_disposition
from openreporting.config import Settings
from openreporting.datasources.base import DataSourceError
from openreporting.datasources.postgres import guard_sql
from openreporting.reporting.excel import _safe, _sheet_title
from openreporting.reporting.fieldcfg import mapped
from openreporting.safe_regex import MAX_PATTERN, RegexError, compile_slashed, compile_user
from openreporting.security import create_user
from openreporting.series_functions import bucket_key
from openreporting.web import create_app

EDITOR = ("editor1", "an-editor-password-123")
VIEWER = ("viewer1", "a-viewer-password-1234")
CPU_TARGET = {
    "refId": "A",
    "datasource": {"uid": "testdata"},
    "group": {"filter": "Linux servers"},
    "host": {"filter": "/.*/"},
    "item": {"filter": "CPU utilization"},
}


@pytest.fixture
def web(tmp_path):
    settings = replace(Settings.from_env(), data_dir=tmp_path, secure_cookie=False, zabbix_url="", zabbix_token_file="", provision_testdata=True)
    app = create_app(settings)
    create_user(settings, *EDITOR, "editor")
    create_user(settings, *VIEWER, "viewer")
    with TestClient(app, base_url="http://localhost") as http:
        yield http


def login(http, credentials):
    res = http.post("/api/login", json={"username": credentials[0], "password": credentials[1]})
    assert res.status_code == 200, res.text
    return {"X-CSRF-Token": res.json()["csrf"]}


def saved_dashboard(http):
    headers = login(http, EDITOR)
    model = {
        "title": "Viewer test",
        "templating": {"list": [{"name": "group", "type": "custom", "query": "Linux servers,WAN Routers", "current": {"value": "Linux servers"}}]},
        "panels": [{"id": 7, "type": "timeseries", "title": "CPU", "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8}, "targets": [CPU_TARGET]}],
    }
    res = http.post("/api/dashboards/db", headers=headers, json={"dashboard": model})
    assert res.status_code == 200, res.text
    http.post("/api/logout", headers=headers)
    return res.json()["uid"]


def query_body(**extra):
    return {"range": {"from": "now-1h", "to": "now"}, "maxDataPoints": 100, "targets": [CPU_TARGET], **extra}


def test_viewer_cannot_run_ad_hoc_queries(web):
    saved_dashboard(web)
    headers = login(web, VIEWER)
    assert web.post("/api/ds/query", headers=headers, json=query_body()).status_code == 403
    find = web.post("/api/datasources/testdata/metric-find", headers=headers, json={"query": "{*}", "range": {"from": "now-1h", "to": "now"}})
    assert find.status_code == 403
    resolve = web.post("/api/dashboards/variables/resolve", headers=headers, json={"dashboard": {"templating": {"list": []}}, "overrides": {}})
    assert resolve.status_code == 403


def test_viewer_runs_the_saved_panel_not_the_posted_targets(web):
    uid = saved_dashboard(web)
    headers = login(web, VIEWER)
    # The posted target asks for another item; the server must run the stored panel definition instead.
    forged = {**CPU_TARGET, "item": {"filter": "/.*/"}, "functions": [{"name": "setAlias", "params": ["forged"]}]}
    res = web.post("/api/ds/query", headers=headers, json=query_body(dashboardUid=uid, panelId=7, targets=[forged]))
    assert res.status_code == 200, res.text
    names = {frame["name"] for frame in res.json()["frames"]}
    assert names and "forged" not in names
    assert all("CPU" in name for name in names)
    missing = web.post("/api/ds/query", headers=headers, json=query_body(dashboardUid=uid, panelId=99))
    assert missing.status_code == 404
    variables = web.post("/api/dashboards/variables/resolve", headers=headers, json={"uid": uid, "dashboard": {}, "overrides": {"group": "WAN Routers"}})
    assert variables.status_code == 200
    assert variables.json()["variables"]["group"]["value"] == "WAN Routers"


def test_report_run_history_endpoint(web):
    uid = saved_dashboard(web)
    headers = login(web, EDITOR)
    rid = web.post("/api/dash-reports", headers=headers, json={"name": "Geçmiş", "dashboard_uid": uid, "formats": ["pdf"]}).json()["id"]
    run = web.post(f"/api/dash-reports/{rid}/runs", headers=headers, json={})
    assert run.status_code == 200, run.text
    runs = web.get(f"/api/dash-reports/{rid}/runs")
    assert runs.status_code == 200, runs.text
    assert [r["id"] for r in runs.json()] == [run.json()["run_id"]]
    web.post("/api/logout", headers=headers)
    login(web, VIEWER)
    seen = web.get(f"/api/dash-reports/{rid}/runs")
    assert seen.status_code == 200 and seen.json()[0]["recipients"] == []


def test_no_route_is_bound_to_a_private_helper(web):
    from fastapi.routing import APIRoute

    endpoints = [r.endpoint.__name__ for r in web.app.routes if isinstance(r, APIRoute)]
    assert endpoints and not [name for name in endpoints if name.startswith("_")]


def test_editor_keeps_ad_hoc_queries(web):
    headers = login(web, EDITOR)
    res = web.post("/api/ds/query", headers=headers, json=query_body())
    assert res.status_code == 200 and res.json()["frames"]


def test_strict_interpolation_forces_quoted_sql():
    variables = {"host": {"value": "x'; DROP TABLE t; --"}}
    loose = templating.interpolate("SELECT ${host:raw}", variables, default_format="sqlstring")
    strict = templating.interpolate("SELECT ${host:raw}", variables, default_format="sqlstring", strict=True)
    assert "DROP TABLE t; --" in loose and not loose.startswith("SELECT '")
    assert strict == "SELECT 'x''; DROP TABLE t; --'"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT E'\\'' ; DELETE FROM t",
        "SELECT $q$ ; $q$; DROP TABLE t",
        "SELECT U&'\\0027'",
        "SELECT 1; DROP TABLE t",
    ],
)
def test_guard_sql_rejects_quote_tricks(sql):
    with pytest.raises(DataSourceError):
        guard_sql(sql)


def test_guard_sql_keeps_ordinary_literals():
    assert guard_sql("SELECT 'it''s' AS v, \"Name\" FROM t") == "SELECT 'it''s' AS v, \"Name\" FROM t"


def test_turkish_report_names_in_download_header():
    header = content_disposition("Ağ Şube Raporu İç", "pdf")
    header.encode("latin-1")  # must be a valid HTTP header value
    assert 'filename="Ag Sube Raporu Ic.pdf"' in header
    assert "filename*=UTF-8''A%C4%9F%20%C5%9Eube%20Raporu%20%C4%B0%C3%A7.pdf" in header
    assert '"' not in content_disposition('a"b', "csv").split("filename=")[1].strip('"').split('";')[0]


def test_daily_buckets_follow_the_dashboard_zone():
    tz = "Europe/Istanbul"
    moment = datetime(2026, 10, 24, 1, 30, tzinfo=timezone.utc)  # 04:30 in Istanbul
    anchor = query_engine.local_midnight_ms(moment, tz)
    assert anchor == int(datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc).timestamp() * 1000)
    day = 86_400_000
    ts = int(moment.timestamp() * 1000)
    assert bucket_key(ts, day, anchor) == anchor
    assert bucket_key(ts, day) != anchor  # a UTC-anchored bucket would start three hours later


def test_value_mappings_match_float_values():
    mappings = [{"type": "value", "options": {"1": {"text": "UP"}, "0": {"text": "DOWN"}}}]
    assert mapped(1.0, mappings)["text"] == "UP"
    assert mapped(0.0, mappings)["text"] == "DOWN"
    assert mapped(2.5, mappings) is None


def test_excel_cells_are_sanitised():
    assert _safe('=HYPERLINK("http://x")') == '\'=HYPERLINK("http://x")'
    assert _safe("@SUM(A1)").startswith("'")
    assert _safe("ok\x00\x07text") == "okt" + "ext"
    assert _safe(-5) == -5
    used = set()
    first = _sheet_title("=cmd|' /C calc'!A0", used)
    assert first[0] not in "=+-@'" and "/" not in first
    assert _sheet_title("=cmd|' /C calc'!A0", used).endswith(" 2")


def test_user_regex_limits():
    with pytest.raises(RegexError):
        compile_user("a" * (MAX_PATTERN + 1))
    with pytest.raises(RegexError):
        compile_user("(unclosed")
    rx = compile_slashed("/^cpu.*/i")
    assert rx.search("CPU utilization") and not rx.search("memory")


def test_time_shift_moves_points_back_into_the_window(tmp_path):
    settings = replace(Settings.from_env(), data_dir=tmp_path, zabbix_url="", zabbix_token_file="", provision_testdata=True)
    from openreporting import datasources
    from openreporting.db import init_db

    init_db(settings)
    datasources.provision(settings)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)  # the engine only honours a "now" close to real time
    base = {"range": {"from": "now-1h", "to": "now"}, "now": now_ms, "maxDataPoints": 60, "timezone": "UTC"}
    target = {"refId": "A", "datasource": {"uid": "testdata"}, "scenario": "sine"}
    plain = query_engine.run(settings, {**base, "targets": [target]})
    shifted = query_engine.run(settings, {**base, "targets": [{**target, "functions": [{"name": "timeShift", "params": ["1h"]}]}]})
    assert shifted["results"]["A"]["error"] is None
    start = now_ms - int(timedelta(hours=1).total_seconds() * 1000)
    points = shifted["frames"][0]["points"]
    assert points and all(start - 120_000 <= t <= now_ms + 120_000 for t, _ in points)
    # Shifted data is drawn on the current window's time axis, not an hour earlier.
    assert abs(points[-1][0] - plain["frames"][0]["points"][-1][0]) <= 120_000
