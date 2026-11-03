"""Data lake / search / time-series sources: request shape, read-only guards, auth, paging and parsing.

The HTTP layer is replaced by a recorder so the tests assert exactly what would be sent on the wire.
"""

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from openreporting import datasources
from openreporting.config import Settings
from openreporting.datasources.base import DataSourceError, QueryContext
from openreporting.datasources.http_sources import HTTPSource
from openreporting.datasources.postgres import expand_macros
from openreporting.datasources.search_tsdb import ElasticsearchDataSource, GraphiteDataSource, InfluxDBDataSource
from openreporting.datasources.sql_engines import ClickHouseDataSource, DatabricksDataSource, TrinoDataSource, convert_rows, parse_time

END = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
START = END - timedelta(hours=1)


@pytest.fixture
def settings():
    return replace(Settings.from_env(), max_rows=100, allow_http_datasources=False)


def ctx(**kw):
    return QueryContext(start=START, end=END, interval_s=60, max_points=500, **kw)


class Recorder:
    """Stands in for HTTPSource.fetch: returns queued responses and records each call."""

    def __init__(self, monkeypatch, *responses):
        self.calls, self.responses = [], list(responses)
        recorder = self

        def fake(source, suffix="", params=None, *, method="GET", body=None, headers=None, raw_path=None, ok=(200,)):
            recorder.calls.append(
                {
                    "suffix": suffix,
                    "params": params,
                    "method": method,
                    "body": body,
                    "headers": {**source.auth_headers(), **(headers or {})},
                    "raw_path": raw_path,
                }
            )
            value = recorder.responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return value if isinstance(value, str) else json.dumps(value)

        monkeypatch.setattr(HTTPSource, "fetch", fake)


def make(cls, settings, url="https://lake.example.com", options=None, secure=None):
    return cls({"uid": "u1", "name": "src", "url": url, "json_data": options or {}}, secure or {}, settings)


# ---- shared SQL behaviour -------------------------------------------------------------------


@pytest.mark.parametrize(
    "dialect,expected",
    [
        ("trino", "from_iso8601_timestamp('2026-01-02T11:00:00+00:00')"),
        ("clickhouse", "parseDateTime64BestEffort('2026-01-02T11:00:00+00:00', 3, 'UTC')"),
        ("databricks", "to_timestamp('2026-01-02T11:00:00+00:00')"),
        ("postgres", "'2026-01-02T11:00:00+00:00'::timestamptz"),
    ],
)
def test_time_macros_use_each_engine_dialect(dialect, expected):
    sql = expand_macros("SELECT 1 WHERE $__timeFilter(ts)", START, END, 60, dialect)
    assert expected in sql and "BETWEEN" in sql


def test_engine_timestamps_and_numbers_are_typed():
    assert parse_time("2026-01-02 11:00:00.123 UTC") == datetime(2026, 1, 2, 11, 0, 0, 123000, tzinfo=timezone.utc)
    assert parse_time("2026-01-02T11:00:00+03:00").utcoffset() == timedelta(hours=3)
    assert parse_time("not a date") == "not a date"
    rows = convert_rows(
        [{"name": "t", "type": "timestamp(3)"}, {"name": "v", "type": "Nullable(UInt64)"}, {"name": "h", "type": "varchar"}],
        [["2026-01-02 11:00:00", "42", "web-1"]],
    )
    assert rows[0][0].tzinfo is timezone.utc and rows[0][1] == 42.0 and rows[0][2] == "web-1"


@pytest.mark.parametrize("cls", [TrinoDataSource, ClickHouseDataSource])
@pytest.mark.parametrize("sql", ["DELETE FROM t", "SELECT 1; DROP TABLE t", "INSERT INTO t VALUES (1)", ""])
def test_sql_engines_refuse_anything_but_one_read_statement(settings, monkeypatch, cls, sql):
    recorder = Recorder(monkeypatch)
    with pytest.raises(DataSourceError):
        make(cls, settings).query({"rawSql": sql}, ctx())
    assert recorder.calls == []  # nothing reached the server


# ---- Trino / Presto (data lake) -------------------------------------------------------------


def test_trino_posts_statement_follows_same_origin_pages_and_builds_series(settings, monkeypatch):
    recorder = Recorder(
        monkeypatch,
        {"nextUri": "https://lake.example.com/v1/statement/queued/q1/1"},
        {
            "columns": [{"name": "time", "type": "timestamp(3)"}, {"name": "value", "type": "double"}],
            "data": [["2026-01-02 11:00:00.000", 1.5]],
            "nextUri": "https://lake.example.com/v1/statement/executing/q1/2",
        },
        {"data": [["2026-01-02 11:01:00.000", 2.5]]},
    )
    source = make(TrinoDataSource, settings, options={"user": "bi", "catalog": "iceberg", "schema": "ops"}, secure={"password": "pw"})
    result = source.query({"refId": "A", "rawSql": "SELECT ts AS time, v AS value FROM m WHERE $__timeFilter(ts)"}, ctx())
    first = recorder.calls[0]
    assert first["method"] == "POST" and first["suffix"] == "/v1/statement" and "from_iso8601_timestamp" in first["body"]
    assert (
        first["headers"]["X-Trino-User"] == "bi" and first["headers"]["X-Trino-Catalog"] == "iceberg" and first["headers"]["Authorization"].startswith("Basic ")
    )
    assert [c["raw_path"] for c in recorder.calls[1:]] == ["/v1/statement/queued/q1/1", "/v1/statement/executing/q1/2"]
    assert result.frames[0]["points"] == [[1767351600000, 1.5], [1767351660000, 2.5]]


def test_trino_never_follows_a_next_uri_to_another_host(settings, monkeypatch):
    Recorder(monkeypatch, {"nextUri": "https://evil.example.net/v1/statement/x"})
    with pytest.raises(DataSourceError, match="başka bir adrese"):
        make(TrinoDataSource, settings).query({"rawSql": "SELECT 1"}, ctx())


def test_trino_errors_and_row_budget_are_reported(settings, monkeypatch):
    Recorder(monkeypatch, {"error": {"message": "Table iceberg.ops.x does not exist"}})
    with pytest.raises(DataSourceError, match="does not exist"):
        make(TrinoDataSource, settings).query({"rawSql": "SELECT 1"}, ctx())
    Recorder(monkeypatch, {"columns": [{"name": "a", "type": "bigint"}], "data": [[i] for i in range(101)], "nextUri": "https://lake.example.com/v1/x"}, "")
    with pytest.raises(DataSourceError, match="Satır sınırı"):
        make(TrinoDataSource, settings).query({"rawSql": "SELECT a FROM t", "format": "table"}, ctx())


def test_presto_flavor_uses_presto_headers(settings, monkeypatch):
    recorder = Recorder(monkeypatch, {"columns": [{"name": "a", "type": "bigint"}], "data": [[1]]})
    make(TrinoDataSource, settings, options={"flavor": "presto", "user": "u"}, secure={"token": "t"}).query(
        {"rawSql": "SELECT 1 AS a", "format": "table"}, ctx()
    )
    headers = recorder.calls[0]["headers"]
    assert headers["X-Presto-User"] == "u" and headers["Authorization"] == "Bearer t" and "X-Trino-User" not in headers


# ---- Databricks SQL ---------------------------------------------------------------------------


def test_databricks_polls_until_done_and_reads_inline_chunks(settings, monkeypatch):
    monkeypatch.setattr("openreporting.datasources.sql_engines.time.sleep", lambda _s: None)
    recorder = Recorder(
        monkeypatch,
        {"statement_id": "01ef-abc", "status": {"state": "PENDING"}},
        {
            "statement_id": "01ef-abc",
            "status": {"state": "SUCCEEDED"},
            "manifest": {"schema": {"columns": [{"name": "host", "type_name": "STRING"}, {"name": "cpu", "type_name": "DOUBLE"}]}},
            "result": {"data_array": [["web-1", "12.5"]], "next_chunk_internal_link": "/api/2.0/sql/statements/01ef-abc/result/chunks/1"},
        },
        {"data_array": [["web-2", "20"]]},
    )
    source = make(
        DatabricksDataSource, settings, url="https://adb-1.azuredatabricks.net", options={"warehouse_id": "abc123", "catalog": "main"}, secure={"token": "dapi"}
    )
    result = source.query({"rawSql": "SELECT host, cpu FROM m", "format": "table"}, ctx())
    sent = json.loads(recorder.calls[0]["body"])
    assert sent["warehouse_id"] == "abc123" and sent["disposition"] == "INLINE" and sent["row_limit"] == 101 and sent["catalog"] == "main"
    assert recorder.calls[0]["headers"]["Authorization"] == "Bearer dapi"
    assert recorder.calls[1]["suffix"] == "/api/2.0/sql/statements/01ef-abc"
    assert result.frames[0]["rows"] == [["web-1", 12.5], ["web-2", 20.0]]


def test_databricks_refuses_foreign_chunk_links_and_reports_failures(settings, monkeypatch):
    Recorder(monkeypatch, {"statement_id": "s1", "status": {"state": "FAILED", "error": {"message": "PERMISSION_DENIED"}}})
    with pytest.raises(DataSourceError, match="PERMISSION_DENIED"):
        make(DatabricksDataSource, settings, options={"warehouse_id": "w"}).query({"rawSql": "SELECT 1"}, ctx())
    Recorder(
        monkeypatch,
        {"statement_id": "s1", "status": {"state": "SUCCEEDED"}, "manifest": {}, "result": {"data_array": [], "next_chunk_internal_link": "/api/2.0/other"}},
    )
    with pytest.raises(DataSourceError, match="beklenmeyen"):
        make(DatabricksDataSource, settings, options={"warehouse_id": "w"}).query({"rawSql": "SELECT 1"}, ctx())


# ---- ClickHouse -------------------------------------------------------------------------------


def test_clickhouse_runs_read_only_with_row_cap_and_header_auth(settings, monkeypatch):
    recorder = Recorder(
        monkeypatch, {"meta": [{"name": "time", "type": "DateTime"}, {"name": "value", "type": "Float64"}], "data": [["2026-01-02T11:00:00Z", 3]]}
    )
    source = make(ClickHouseDataSource, settings, options={"user": "reader", "database": "logs"}, secure={"password": "pw"})
    result = source.query({"rawSql": "SELECT $__timeGroup(ts, 1m) AS time, count() AS value FROM t WHERE $__timeFilter(ts) GROUP BY time"}, ctx())
    call = recorder.calls[0]
    assert "readonly=2" in call["suffix"] and "max_result_rows=101" in call["suffix"] and "result_overflow_mode=throw" in call["suffix"]
    assert (
        call["headers"]["X-ClickHouse-User"] == "reader" and call["headers"]["X-ClickHouse-Key"] == "pw" and call["headers"]["X-ClickHouse-Database"] == "logs"
    )
    assert "toStartOfInterval(ts, INTERVAL 60 SECOND)" in call["body"]
    assert result.frames[0]["points"] == [[1767351600000, 3.0]]


def test_clickhouse_readonly_profile_sends_no_settings(settings, monkeypatch):
    recorder = Recorder(monkeypatch, {"meta": [{"name": "a", "type": "UInt8"}], "data": [[1]]})
    make(ClickHouseDataSource, settings, options={"readonly_profile": True}).query({"rawSql": "SELECT 1 AS a", "format": "table"}, ctx())
    assert "readonly" not in recorder.calls[0]["suffix"]


# ---- Elasticsearch / OpenSearch ---------------------------------------------------------------


def test_elasticsearch_metrics_split_by_terms_with_api_key(settings, monkeypatch):
    buckets = {"buckets": [{"key": 1767351600000, "doc_count": 4, "v": {"value": 120.0}}]}
    recorder = Recorder(monkeypatch, {"_shards": {"failed": 0}, "aggregations": {"g": {"buckets": [{"key": "web-1", "h": buckets}]}}})
    source = make(ElasticsearchDataSource, settings, options={"auth_mode": "apikey", "time_field": "@timestamp"}, secure={"token": "k=="})
    result = source.query({"index": "logs-*", "query": "level:error", "metric": "avg", "field": "latency_ms", "groupBy": "host.keyword"}, ctx())
    call = recorder.calls[0]
    body = json.loads(call["body"])
    assert call["method"] == "POST" and call["suffix"] == "/logs-*/_search" and call["headers"]["Authorization"] == "ApiKey k=="
    assert body["query"]["bool"]["filter"][1]["query_string"]["query"] == "level:error"
    assert body["aggs"]["g"]["terms"]["field"] == "host.keyword" and body["aggs"]["g"]["aggs"]["h"]["aggs"]["v"] == {"avg": {"field": "latency_ms"}}
    assert result.frames[0]["name"] == "web-1 · avg(latency_ms)" and result.frames[0]["points"] == [[1767351600000, 120.0]]


@pytest.mark.parametrize("index", ["../_cluster", "logs/_delete_by_query", "LOGS", "_all?x", ""])
def test_elasticsearch_index_cannot_reach_other_apis(settings, monkeypatch, index):
    recorder = Recorder(monkeypatch)
    with pytest.raises(DataSourceError):
        make(ElasticsearchDataSource, settings).query({"index": index}, ctx())
    assert recorder.calls == []


def test_elasticsearch_logs_mode_flattens_sources_and_rejects_partial_results(settings, monkeypatch):
    Recorder(monkeypatch, {"hits": {"hits": [{"_source": {"@timestamp": "2026-01-02T11:00:00Z", "message": "boom", "http": {"status": 500}}}]}})
    result = make(ElasticsearchDataSource, settings, options={"index": "logs-*"}).query({"mode": "logs"}, ctx())
    frame = result.frames[0]
    assert [c["name"] for c in frame["columns"]] == ["time", "message", "http"] and frame["rows"][0] == [1767351600000, "boom", '{"status": 500}']
    Recorder(monkeypatch, {"_shards": {"failed": 2}, "aggregations": {}})
    with pytest.raises(DataSourceError, match="shard"):
        make(ElasticsearchDataSource, settings, options={"index": "logs-*"}).query({}, ctx())


# ---- InfluxDB ---------------------------------------------------------------------------------


def test_influxql_macros_series_and_token_auth(settings, monkeypatch):
    recorder = Recorder(
        monkeypatch, {"results": [{"series": [{"name": "cpu", "tags": {"host": "a"}, "columns": ["time", "mean"], "values": [[1767351600000, 7.5]]}]}]}
    )
    source = make(InfluxDBDataSource, settings, options={"database": "telegraf", "auth_mode": "token"}, secure={"token": "tok"})
    result = source.query({"query": 'SELECT mean("usage") FROM "cpu" WHERE $timeFilter GROUP BY time($__interval), "host"'}, ctx())
    params = recorder.calls[0]["params"]
    assert params["db"] == "telegraf" and params["epoch"] == "ms" and "time >= 1767351600000ms" in params["q"] and "time(60s)" in params["q"]
    assert recorder.calls[0]["headers"]["Authorization"] == "Token tok"
    assert result.frames[0]["name"] == "cpu.mean host=a" and result.frames[0]["points"] == [[1767351600000, 7.5]]


@pytest.mark.parametrize("q", ['SELECT * INTO "x" FROM "cpu"', "DROP MEASUREMENT cpu", "SELECT 1; DROP DATABASE d", "CREATE USER x"])
def test_influxql_rejects_writes(settings, monkeypatch, q):
    recorder = Recorder(monkeypatch)
    with pytest.raises(DataSourceError):
        make(InfluxDBDataSource, settings, options={"database": "d"}).query({"query": q}, ctx())
    assert recorder.calls == []


# ---- Graphite ---------------------------------------------------------------------------------


def test_graphite_render_targets_and_metric_find(settings, monkeypatch):
    recorder = Recorder(
        monkeypatch, [{"target": "servers.web.cpu", "datapoints": [[1.0, 1767351600], [None, 1767351660]]}], [{"text": "web", "id": "servers.web"}]
    )
    source = make(GraphiteDataSource, settings)
    result = source.query({"target": "servers.*.cpu\nsumSeries(servers.*.mem)"}, ctx())
    suffix = recorder.calls[0]["suffix"]
    assert suffix.startswith("/render?") and suffix.count("target=") == 2 and "format=json" in suffix
    assert result.frames[0]["points"] == [[1767351600000, 1.0], [1767351660000, None]]
    assert source.metric_find("servers.*") == [{"text": "web", "value": "servers.web"}]


# ---- registry / validation --------------------------------------------------------------------


def test_new_types_are_registered_with_secrets_and_validated(settings):
    for kind in ("trino", "databricks", "clickhouse", "elasticsearch", "influxdb", "graphite"):
        assert kind in datasources.TYPES and kind in datasources.SECURE_FIELDS
    url, clean = datasources.validate("trino", "https://trino.example.com:8443", {"user": "bi", "catalog": "hive"}, settings)
    assert clean["user"] == "bi" and clean["flavor"] == "trino"
    with pytest.raises(DataSourceError):
        datasources.validate("trino", "http://trino.example.com", {}, settings)  # HTTPS only by default
    with pytest.raises(DataSourceError):
        datasources.validate("databricks", "https://adb.example.com", {"warehouse_id": "bad id!"}, settings)
    with pytest.raises(DataSourceError):
        datasources.validate("influxdb", "https://influx.example.com", {}, settings)
    with pytest.raises(DataSourceError):
        datasources.validate("elasticsearch", "https://es.example.com", {"auth_mode": "basic"}, settings)
    with pytest.raises(DataSourceError):
        datasources.validate("clickhouse", "https://ch.example.com", {"user": "a\r\nX-Evil: 1"}, settings)


def test_variable_formats_keep_values_inert_in_each_engine():
    from openreporting.templating import format_values

    # Backslash escapes in ClickHouse / Spark SQL literals must not break out of the string.
    assert format_values(["a'b\\"], "sqlstring_escaped") == "'a''b\\\\'"  # one backslash in, two out
    assert format_values(["x", "y"], "sqlstring_escaped", multi=True) == "'x','y'"
    # A slash would end an InfluxQL /regex/ literal.
    assert format_values(["a/b.c"], "influxregex") == r"a\/b\.c"
    assert format_values(['say "hi"'], "lucene") == '("say \\"hi\\"")'
    assert ClickHouseDataSource.default_format == DatabricksDataSource.default_format == "sqlstring_escaped"
    assert TrinoDataSource.default_format == "sqlstring" and InfluxDBDataSource.default_format == "influxregex"
