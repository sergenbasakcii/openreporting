"""Dashboard version diff: reviewer-readable changes, runtime state ignored, folder ACL enforced."""

from dataclasses import replace

import pytest

from openreporting import dashboards, security
from openreporting.config import Settings
from openreporting.dashboard_diff import diff
from openreporting.db import connect, init_db, transaction


def model(**overrides):
    base = {
        "title": "Ops",
        "tags": ["net"],
        "templating": {"list": [{"name": "host", "type": "query", "query": "{Linux}{*}", "current": {"value": "a"}}]},
        "panels": [
            {"id": 1, "type": "timeseries", "title": "CPU", "targets": [{"refId": "A", "item": {"filter": "CPU"}}], "gridPos": {"x": 0}},
            {"id": 9, "type": "row", "title": "Hidden", "collapsed": True, "panels": [{"id": 10, "type": "stat", "title": "Disk"}]},
        ],
    }
    base.update(overrides)
    return base


def texts(changes):
    return [c["text"] for c in changes]


def test_identical_models_and_runtime_selection_produce_no_changes():
    changed_selection = model()
    changed_selection["templating"]["list"][0]["current"] = {"value": "b"}
    assert diff(model(), changed_selection) == []


def test_panel_query_title_and_nested_row_changes_are_named():
    new = model()
    new["panels"][0] = {**new["panels"][0], "targets": [{"refId": "A", "item": {"filter": "Memory"}}]}
    new["panels"][1]["panels"][0] = {**new["panels"][1]["panels"][0], "title": "Disk free"}
    assert texts(diff(model(), new)) == ["Panel 'CPU': sorgular değişti", "Panel 'Disk free': başlık değişti"]


def test_added_removed_panels_variables_and_dashboard_fields():
    new = model(title="Ops v2", templating={"list": [{"name": "group", "type": "custom", "query": "a,b"}]})
    new["panels"] = new["panels"][:1] + [{"id": 2, "type": "table", "title": "Errors"}]
    result = diff(model(), new)
    assert {c["kind"] for c in result} == {"added", "removed", "changed"}
    assert "Başlık değişti" in texts(result)
    assert "Değişken $host kaldırıldı" in texts(result) and "Değişken $group eklendi" in texts(result)
    assert "Panel 'Errors' eklendi" in texts(result) and "Panel 'Hidden' kaldırıldı" in texts(result)


def test_version_diff_endpoint_compares_saved_versions_and_respects_folder_access(tmp_path):
    settings = replace(Settings.from_env(), data_dir=tmp_path / "data", database_url="", secret_key_file="")
    init_db(settings)
    admin = {"id": security.create_user(settings, "diffadmin", "a-long-enough-password", "admin"), "role": "admin"}
    viewer = {"id": security.create_user(settings, "diffviewer", "a-long-enough-password", "viewer"), "role": "viewer"}
    folder = dashboards.save_folder(settings, admin, "Private ops")
    saved = dashboards.save(settings, admin, {"uid": "diffed", **model()}, folder_uid=folder["uid"])
    current = dashboards.get(settings, saved["uid"], admin)["dashboard"]
    dashboards.save(settings, admin, {**current, "title": "Ops renamed"}, folder_uid=dashboards.KEEP_FOLDER)
    result = dashboards.version_diff(settings, "diffed", 1, None, admin)
    assert result["from"] == 1 and result["to"] == 2 and texts(result["changes"]) == ["Başlık değişti"]
    with connect(settings) as db, transaction(db):
        folder_id = db.execute("SELECT folder_id FROM dashboards WHERE uid='diffed'").fetchone()["folder_id"]
        db.execute("INSERT INTO folder_policy(folder_id,restricted,revision) VALUES(?,1,1)", (folder_id,))
    with pytest.raises(Exception) as denied:
        dashboards.version_diff(settings, "diffed", 1, None, viewer)
    assert getattr(denied.value, "status_code", None) in (403, 404)
