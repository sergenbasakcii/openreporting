"""Previous-period comparison (query expansion, deltas, viewer path) and the smart narrative."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from openreporting import query_engine, security
from openreporting.config import Settings
from openreporting.reporting.compare import comparison_deltas, delta_text
from openreporting.reporting.fieldcfg import reduced_items
from openreporting.reporting.narrative import sentences
from openreporting.web import create_app

PASSWORD = "disposable-compare-password"
DS = {"uid": "testdata", "type": "testdata"}


def ts(name, points, previous=False):
    frame = {"type": "timeseries", "name": name, "points": points, "labels": {}, "unit": ""}
    return query_engine.mark_previous(frame) if previous else frame


@pytest.fixture
def settings(tmp_path):
    return replace(
        Settings.from_env(), data_dir=tmp_path, database_url="", secret_key_file="", secure_cookie=False, mfa_required_roles=(), provision_testdata=True
    )


def test_compare_adds_a_shifted_twin_per_visible_query_and_marks_its_frames(settings):
    create_app(settings)  # provisions the TestData source
    request = {
        "targets": [{"refId": "A", "scenario": "sine", "datasource": DS}, {"refId": "B", "scenario": "sine", "datasource": DS, "hide": True}],
        "range": {"from": "now-6h", "to": "now"},
        "compare": "previous",
    }
    out = query_engine.run(settings, request)
    assert set(out["results"]) == {"A", "B", "A__prev"}  # hidden queries get no twin
    previous = [f for f in out["frames"] if (f.get("meta") or {}).get("previous")]
    current = [f for f in out["frames"] if not (f.get("meta") or {}).get("previous")]
    assert previous and all(f["name"].endswith(" (önceki dönem)") for f in previous)
    # The twin was queried one range earlier and aligned onto the current window.
    assert abs(previous[0]["points"][-1][0] - current[0]["points"][-1][0]) < 120_000


def test_compare_is_opt_in_and_bounded():
    targets = [{"refId": chr(65 + i)} for i in range(query_engine.MAX_TARGETS)]
    ctx = type("Ctx", (), {"start": __import__("datetime").datetime(2026, 1, 1), "end": __import__("datetime").datetime(2026, 1, 2)})()
    assert query_engine.with_previous_period(targets, ctx, None, None) is targets
    with pytest.raises(query_engine.QueryError):
        query_engine.with_previous_period(targets, ctx, None, "previous")
    twin = query_engine.with_previous_period([{"refId": "A", "functions": [{"name": "timeShift", "params": ["1h"]}]}], ctx, None, "previous")[1]
    assert twin["functions"] == [{"name": "timeShift", "params": ["86400s"]}]  # the panel's own shift is replaced, not stacked


def test_stat_deltas_and_previous_frames_stay_out_of_reducers():
    panel = {"type": "stat", "options": {"compare": "previous", "reduceOptions": {"calcs": ["mean"]}}, "fieldConfig": {"defaults": {}}}
    frames = [
        ts("web-1", [[1, 110.0], [2, 130.0]]),
        ts("web-2", [[1, 50.0]]),
        ts("web-1", [[1, 100.0]], previous=True),
        ts("web-2", [[1, 100.0]], previous=True),
    ]
    items = reduced_items(panel, frames)
    assert [i["name"] for i in items] == ["web-1", "web-2"]
    deltas = comparison_deltas(panel, frames, items)
    assert deltas[0] == pytest.approx(0.2) and deltas[1] == pytest.approx(-0.5)
    assert delta_text(0.2, "down") == ("▲ %20,0 önceki döneme göre", "bad")
    assert delta_text(-0.5, "down")[1] == "good" and delta_text(0.1)[1] == "neutral"
    assert comparison_deltas({**panel, "options": {}}, frames, items) == {}


def test_viewers_get_the_comparison_from_the_saved_panel(settings):
    app = create_app(settings)
    security.create_user(settings, "editor1", PASSWORD, "editor")
    security.create_user(settings, "viewer1", PASSWORD, "viewer")

    def client(name):
        http = TestClient(app, base_url="http://127.0.0.1")
        http.headers["X-CSRF-Token"] = http.post("/api/login", json={"username": name, "password": PASSWORD}).json()["csrf"]
        return http

    panel = {"id": 1, "type": "stat", "options": {"compare": "previous"}, "datasource": DS, "targets": [{"refId": "A", "scenario": "sine", "datasource": DS}]}
    assert (
        client("editor1").post("/api/dashboards/db", json={"dashboard": {"uid": "cmp", "title": "Cmp", "panels": [panel]}, "overwrite": True}).status_code
        == 200
    )
    res = client("viewer1").post(
        "/api/ds/query", json={"targets": [{"refId": "Z"}], "dashboardUid": "cmp", "panelId": 1, "range": {"from": "now-1h", "to": "now"}}
    )
    assert res.status_code == 200, res.text
    assert "A__prev" in res.json()["results"]


def test_narrative_states_only_facts_from_the_data():
    panel = {
        "type": "narrative",
        "title": "CPU",
        "options": {},
        "fieldConfig": {"defaults": {"unit": "percent", "thresholds": {"steps": [{"color": "green", "value": None}, {"color": "red", "value": 90}]}}},
    }
    frames = [
        ts("web-1", [[0, 10.0], [3_600_000, 20.0], [7_200_000, 40.0], [10_800_000, 95.0]]),
        ts("web-2", [[0, 5.0], [3_600_000, 5.0], [7_200_000, 6.0], [10_800_000, 6.0]]),
        ts("web-1", [[0, 10.0]], previous=True),
    ]
    text = sentences(panel, frames, "UTC")
    assert text[0].startswith("CPU dönem boyunca ortalama") and "web-1" in text[0] and "95%" in text[0]
    assert "En yüksek ortalama web-1" in text[1] and "2 seri incelendi" in text[1]
    assert "arttı" in text[2]
    assert "1 seri son değerde 90% eşiğinin üzerinde: web-1." == text[3]
    assert text[4].startswith("Önceki döneme göre ortalama %")
    assert sentences(panel, [ts("x", [[0, None]])], "UTC") == []
