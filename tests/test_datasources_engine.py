"""Datasource registry, Zabbix/TestData/Postgres adapters, query engine and dashboard runtime."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from openreporting import dashboard_runtime, dashboards, datasources, query_engine
from openreporting.config import Settings
from openreporting.datasources.base import DataSourceError, QueryContext, compile_filter
from openreporting.datasources.postgres import expand_macros, guard_sql, rows_to_frames
from openreporting.datasources.zabbix import ZabbixApi, normalize_target, parse_find_query
from openreporting.db import connect, init_db
from openreporting.security import create_user


@pytest.fixture
def settings(tmp_path):
    s = replace(Settings.from_env(), data_dir=tmp_path, secure_cookie=False, zabbix_url="", zabbix_token_file="", provision_testdata=True)
    init_db(s)
    datasources.provision(s)
    return s


def fake_zabbix(method, params):
    groups = [{"groupid": "1", "name": "Linux servers"}, {"groupid": "2", "name": "Routers"}]
    hosts = [{"hostid": "10", "host": "web01", "name": "Web 01", "status": "0", "hostgroups": [{"groupid": "1"}]},
             {"hostid": "11", "host": "web02", "name": "Web 02", "status": "0", "hostgroups": [{"groupid": "1"}]},
             {"hostid": "20", "host": "rtr", "name": "Router", "status": "0", "hostgroups": [{"groupid": "2"}]}]
    items = [{"itemid": "100", "hostid": "10", "name": "CPU utilization", "key_": "system.cpu.util", "units": "%",
              "value_type": "0", "status": "0", "lastvalue": "12.5", "lastclock": "1770000000",
              "tags": [{"tag": "component", "value": "cpu"}]},
             {"itemid": "101", "hostid": "11", "name": "CPU utilization", "key_": "system.cpu.util", "units": "%",
              "value_type": "0", "status": "0", "lastvalue": "40", "lastclock": "1770000000",
              "tags": [{"tag": "component", "value": "cpu"}]},
             {"itemid": "102", "hostid": "11", "name": "Agent version", "key_": "agent.version", "units": "",
              "value_type": "1", "status": "0", "lastvalue": "7.0", "lastclock": "1770000000", "tags": []},
             {"itemid": "200", "hostid": "20", "name": "CPU utilization", "key_": "cpu", "units": "%",
              "value_type": "3", "status": "0", "tags": []}]
    if method == "apiinfo.version":
        return "7.0.5"
    if method == "hostgroup.get":
        return groups
    if method == "host.get":
        wanted = set(params.get("groupids") or [])
        return [h for h in hosts if {g["groupid"] for g in h["hostgroups"]} & wanted]
    if method == "item.get":
        wanted = set(params.get("hostids") or [])
        return [i for i in items if i["hostid"] in wanted]
    if method == "history.get":
        rows = []
        for itemid in params["itemids"]:
            for n in range(5):
                rows.append({"itemid": itemid, "clock": str(params["time_from"] + n * 60), "value": str(10 * n + int(itemid) % 7)})
        return rows
    if method == "trend.get":
        return [{"itemid": i, "clock": str(params["time_from"]), "num": "60", "value_min": "1", "value_avg": "5",
                 "value_max": "9"} for i in params["itemids"]]
    if method == "trigger.get":
        return [{"triggerid": "7", "description": "High CPU", "priority": "4", "lastchange": "1770000000",
                 "hosts": [{"hostid": "11", "name": "Web 02"}]}]
    raise AssertionError(method)


def add_zabbix(settings):
    return datasources.save(settings, "tester", {"type": "zabbix", "name": "Zabbix Prod",
                                                 "url": "https://zbx.example.org/api_jsonrpc.php",
                                                 "jsonData": {"trends_from": "7d", "trends_range": "4d"},
                                                 "secureJsonData": {"token": "super-secret-token"}})


def test_provisioned_testdata_and_secret_never_listed(settings):
    uid = add_zabbix(settings)
    listing = {d["uid"]: d for d in datasources.list_all(settings)}
    assert listing["testdata"]["readOnly"] is True
    assert listing[uid]["secureJsonFields"] == {"token": True}
    assert "super-secret-token" not in json.dumps(listing)
    with connect(settings) as db:
        stored = db.execute("SELECT secure_json FROM datasources WHERE uid=?", (uid,)).fetchone()[0]
    assert "super-secret-token" not in stored
    datasources.save(settings, "tester", {"type": "zabbix", "name": "Zabbix Prod",
                                          "url": "https://zbx.example.org/api_jsonrpc.php", "jsonData": {}}, uid=uid)
    assert datasources.get(settings, uid).api.token == "super-secret-token"
    with pytest.raises(DataSourceError):
        datasources.save(settings, "t", {"type": "zabbix", "name": "Bad", "url": "http://x/api_jsonrpc.php"})
    with pytest.raises(DataSourceError):
        datasources.delete(settings, "t", "testdata")


def test_zabbix_group_query_regex_tags_and_trends(settings):
    uid = add_zabbix(settings)
    ds = datasources.get(settings, uid, transport=fake_zabbix)
    end = datetime.now(timezone.utc)
    ctx = QueryContext(start=end - timedelta(hours=1), end=end, interval_s=60, max_points=1000)
    target = {"refId": "A", "group": {"filter": "/Linux/"}, "host": {"filter": "*"},
              "item": {"filter": "CPU utilization"}, "itemTag": {"filter": "component: cpu"}}
    result = ds.query(target, ctx)
    assert sorted(f["labels"]["host"] for f in result.frames) == ["Web 01", "Web 02"]
    assert result.frames[0]["labels"]["group"] == "Linux servers"
    assert result.meta["resolution"] == "history"
    old = QueryContext(start=end - timedelta(days=20), end=end, interval_s=3600, max_points=1000)
    assert ds.query(target, old).meta["resolution"] == "trends"
    values = ds.query({**target, "queryType": "2", "item": {"filter": ""}, "itemTag": {"filter": ""}}, ctx)
    assert {r[1] for r in values.frames[0]["rows"]} == {"CPU utilization", "Agent version"}
    problems = ds.query({"refId": "P", "queryType": "problems", "group": "Linux servers"}, ctx)
    assert problems.frames[0]["rows"][0][2] == "High CPU"
    assert [v["text"] for v in ds.metric_find("{Linux servers}{*}")] == ["Web 01", "Web 02"]
    assert parse_find_query("{a}{b}{c}")["type"] == "item"
    ds.max_items = 1
    with pytest.raises(DataSourceError, match="güvenlik sınırı"):
        ds.query(target, ctx)


def test_zabbix_api_refuses_write_methods_and_plain_http():
    api = ZabbixApi("https://z.example/api_jsonrpc.php", "t", transport=lambda m, p: [])
    with pytest.raises(DataSourceError):
        api.call("host.delete", {})
    with pytest.raises(DataSourceError):
        ZabbixApi("http://z.example/api_jsonrpc.php", "t")
    assert normalize_target({"queryType": "3"})["queryType"] == "itemid"


def test_filters_support_regex_glob_and_exact():
    assert compile_filter("/^web\\d+$/i")("WEB01")
    assert compile_filter("web*")("web-01") and not compile_filter("web*")("app")
    assert compile_filter("Exact")("Exact") and not compile_filter("Exact")("exact")


def test_sql_guard_and_macros():
    assert guard_sql("SELECT 1;") == "SELECT 1"
    for bad in ("DELETE FROM t", "SELECT 1; DROP TABLE t", "WITH x AS (DELETE FROM t RETURNING *) SELECT 1",
                "SELECT * INTO new_t FROM t", "COPY t TO '/tmp/x'"):
        with pytest.raises(DataSourceError):
            guard_sql(bad)
    assert guard_sql("SELECT 'a;b' AS v -- comment;\n") == "SELECT 'a;b' AS v"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sql = expand_macros("SELECT $__unixEpochGroupAlias(clock, 5m), avg(value) FROM h WHERE $__unixEpochFilter(clock) "
                        "AND $__timeFilter(ts)", start, start + timedelta(hours=1), 60)
    assert "(floor(clock/300)*300) AS \"time\"" in sql and "clock >= 1767225600" in sql and "BETWEEN" in sql
    with pytest.raises(DataSourceError):
        expand_macros("SELECT $__timeFilter(1;drop)", start, start, 60)
    frames = rows_to_frames(["time", "metric", "value"], [(1767225600, "a", 1.5), (1767225660, "a", None),
                                                          (1767225600, "b", 3)], "time_series", "A")
    assert {f["name"]: len(f["points"]) for f in frames} == {"a": 2, "b": 1}
    table = rows_to_frames(["host", "value"], [("x", 1)], "table", "A")[0]
    assert table["columns"][1]["type"] == "number"


def test_query_engine_testdata_group_report_flow(settings):
    response = query_engine.run(settings, {
        "range": {"from": "now-6h", "to": "now"}, "maxDataPoints": 200,
        "variables": {"group": {"value": "Linux servers"}},
        "targets": [{"refId": "A", "datasource": {"uid": "testdata"}, "group": {"filter": "$group"},
                     "host": {"filter": "/.*/"}, "item": {"filter": "CPU utilization"}},
                    {"refId": "B", "datasource": {"uid": "testdata"}, "group": {"filter": "$group"},
                     "host": {"filter": "/.*/"}, "item": {"filter": "CPU utilization"},
                     "functions": [{"name": "aggregateBy", "params": ["10m", "avg"]}, {"name": "setAlias", "params": ["Grup ortalaması"]}]},
                    {"refId": "C", "datasource": {"type": "__expr__", "uid": "__expr__"}, "type": "math",
                     "expression": "$B * 2", "hide": True}],
        "transformations": [{"id": "filterByRefId", "options": {"include": "A"}},
                            {"id": "reduceByLabel", "options": {"label": "host", "reducer": "max"}}]}, user="t")
    assert response["results"]["A"]["error"] is None
    assert response["results"]["C"]["error"] is None
    table = response["frames"][0]
    assert table["type"] == "table" and len(table["rows"]) == 8
    assert all(row[1] is None or 0 <= row[1] <= 100 for row in table["rows"])


def test_query_engine_reports_bad_target_without_crashing(settings):
    response = query_engine.run(settings, {"range": {"from": "now-1h", "to": "now"},
                                           "targets": [{"refId": "A", "datasource": {"uid": "missing"}},
                                                       {"refId": "B", "datasource": {"uid": "testdata"},
                                                        "scenario": "sine"}]})
    assert "bulunamadı" in response["results"]["A"]["error"]
    assert response["results"]["B"]["error"] is None and response["frames"]


def test_dashboard_import_normalizes_grafana_json(settings):
    grafana = {"__inputs": [{"name": "DS_ZABBIX", "type": "datasource", "pluginId": "alexanderzobnin-zabbix-datasource"}],
               "title": "Imported", "uid": "imp-1", "version": 7,
               "templating": {"list": [{"name": "host", "type": "query", "datasource": "${DS_ZABBIX}",
                                        "query": "{Linux servers}{*}", "multi": True, "includeAll": True}]},
               "panels": [{"id": 3, "type": "graph", "title": "CPU $host", "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
                           "datasource": "${DS_ZABBIX}", "yaxes": [{"format": "percent"}], "fill": 2,
                           "targets": [{"group": {"filter": "Linux servers"}, "host": {"filter": "$host"},
                                        "item": {"filter": "CPU utilization"}, "queryType": "0"}],
                           "repeat": "host"},
                          {"type": "alexanderzobnin-zabbix-triggers-panel", "title": "Problems", "targets": [{}]},
                          {"type": "some-unknown-plugin", "title": "X"}]}
    rows = datasources.list_all(settings)
    mapping = dashboards.import_map(rows, grafana)
    model = dashboards.normalize(grafana, mapping)
    first = model["panels"][0]
    assert first["type"] == "timeseries" and first["fieldConfig"]["defaults"]["unit"] == "percent"
    assert first["fieldConfig"]["defaults"]["custom"]["fillOpacity"] == 20
    assert first["datasource"] == {"uid": "testdata"}
    assert model["panels"][1]["targets"][0]["queryType"] == "problems"
    assert model["panels"][2]["type"] == "text"
    assert len({p["id"] for p in model["panels"]}) == 3


def test_dashboard_versions_conflicts_and_repeat_expansion(settings):
    uid = create_user(settings, "editor1", "an-editor-password-123", "editor")
    user = {"id": uid, "role": "editor"}
    model = {"title": "Group report", "templating": {"list": [
        {"name": "group", "type": "custom", "query": "Linux servers,WAN Routers", "current": {"value": "Linux servers"}},
        {"name": "host", "type": "query", "datasource": {"uid": "testdata"}, "query": "{$group}{*}",
         "multi": True, "includeAll": True, "current": {"value": ["$__all"]}}]},
        "panels": [{"type": "row", "title": "Host $host", "repeat": "host", "gridPos": {"x": 0, "y": 0, "w": 24, "h": 1}},
                   {"type": "stat", "title": "CPU $host", "gridPos": {"x": 0, "y": 1, "w": 6, "h": 4},
                    "targets": [{"datasource": {"uid": "testdata"}, "group": {"filter": "$group"},
                                 "host": {"filter": "$host"}, "item": {"filter": "CPU utilization"}}]}]}
    saved = dashboards.save(settings, user, model, message="ilk")
    loaded = dashboards.get(settings, saved["uid"], user)
    assert loaded["dashboard"]["version"] == 1
    stale = dict(loaded["dashboard"], version=0)
    with pytest.raises(dashboards.VersionConflict):
        dashboards.save(settings, user, stale)
    dashboards.save(settings, user, dict(loaded["dashboard"], title="Group report v2"))
    assert [v["version"] for v in dashboards.versions(settings, saved["uid"])] == [2, 1]
    dashboards.restore(settings, user, saved["uid"], 1)
    assert dashboards.get(settings, saved["uid"], user)["dashboard"]["title"] == "Group report"
    variables, warnings = dashboard_runtime.resolve_variables(settings, loaded["dashboard"])
    assert not warnings and len(variables["host"]["options"]) == 8
    expanded = dashboard_runtime.expand(loaded["dashboard"], variables)
    rows = [p for p in expanded if p["type"] == "row"]
    stats = [p for p in expanded if p["type"] == "stat"]
    assert len(rows) == 8 and len(stats) == 8
    assert stats[0]["title"].startswith("CPU srv-") and stats[0]["scopedVars"]["host"]["value"] == stats[0]["title"][4:]
    assert rows[1]["gridPos"]["y"] > rows[0]["gridPos"]["y"]
    wan, _ = dashboard_runtime.resolve_variables(settings, loaded["dashboard"], {"group": "WAN Routers"})
    assert len(wan["host"]["options"]) == 5


def test_stored_token_is_not_kept_when_the_destination_changes(settings):
    # Editing the URL must not send the old token to the new address.
    uid = add_zabbix(settings)
    moved = {"type": "zabbix", "name": "Zabbix Prod", "url": "https://attacker.example.net/api_jsonrpc.php", "jsonData": {}}
    with pytest.raises(DataSourceError, match="yeniden girilmeli"):
        datasources.save(settings, "tester", moved, uid=uid)
    assert datasources.get(settings, uid).api.token == "super-secret-token"
    datasources.save(settings, "tester", {**moved, "secureJsonData": {"token": "new-token-for-new-host"}}, uid=uid)
    assert datasources.get(settings, uid).api.token == "new-token-for-new-host"
