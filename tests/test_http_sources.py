"""Real local HTTP fixtures: fixed-origin GET, bounds and frame conversion."""
import json
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from openreporting import datasources, db, templating
from openreporting.config import Settings
from openreporting.datasources.base import DataSourceError, QueryContext
from openreporting.datasources.http_sources import safe_peer, validate_http_url


@pytest.fixture
def fixture_source(tmp_path):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization")))
            status = 200
            if self.path.startswith("/api/v1/query_range"):
                payload = {"status":"success","data":{"resultType":"matrix","result":[{"metric":{"job":"test"},"values":[[1000,"2"],[1001,"NaN"]]}]}}
            elif self.path.startswith("/loki/api/v1/query_range"):
                payload = {"status":"success","data":{"resultType":"streams","result":[{"stream":{"job":"test"},"values":[["1000000000","hello"]]}]}}
            elif self.path == "/csv":
                payload = "name,value\nalpha,2\nbeta,\n"
            elif self.path == "/redirect":
                status, payload = 302, "redirect"
            else:
                payload = {"data":[{"name":"alpha","value":2},{"name":"beta","value":None}]}
            self.send_response(status)
            self.end_headers()
            self.wfile.write((json.dumps(payload) if isinstance(payload, dict) else payload).encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings = replace(Settings.from_env(), data_dir=tmp_path, allow_http_datasources=True, allow_loopback_datasources=True, secret_key_file="")
    db.init_db(settings)
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        yield settings, base, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def create(settings, base, kind, path="", **options):
    saved = datasources.save(settings, "test", {"name":kind,"type":kind,"url":base+path,
        "jsonData":options,"secureJsonData":{"token":"fixture-token"}})
    return datasources.get(settings, saved)


def context():
    end = datetime.now(timezone.utc)
    return QueryContext(end-timedelta(hours=1), end, 60, 100)


def test_prometheus_real_get_frames_and_fixed_origin(fixture_source):
    settings, base, requests = fixture_source
    source = create(settings, base, "prometheus")
    result = source.query({"refId":"A","expr":"up","url":"https://other.example.com"}, context())
    assert result.frames[0]["points"] == [[1000000, 2.0], [1001000, None]]
    assert requests[0][0].startswith("/api/v1/query_range?")
    assert requests[0][1] == "Bearer fixture-token"
    assert datasources.list_all(settings)[0]["secureJsonFields"] == {"token": True}
    assert "fixture-token" not in str(datasources.list_all(settings))


def test_loki_and_json_csv_conversion(fixture_source):
    settings, base, _ = fixture_source
    loki = create(settings, base, "loki")
    assert loki.query({"expr":'{job="test"}'}, context()).frames[0]["rows"][0][:2] == [1000, "hello"]
    for kind, path, options in (("httpjson", "/json", {"root":"data"}), ("csv", "/csv", {})):
        source = create(settings, base, kind, path, **options)
        frame = source.query({}, context()).frames[0]
        assert frame["columns"][1]["type"] == "number"
        assert frame["rows"] == [["alpha", 2.0], ["beta", None]]
        assert source.health()["status"] == "ok"


def test_redirect_and_response_budget_are_fail_closed(fixture_source, monkeypatch):
    from openreporting.datasources import http_sources
    settings, base, _ = fixture_source
    source = create(settings, base, "httpjson", "/redirect")
    with pytest.raises(DataSourceError, match="302"):
        source.query({}, context())
    monkeypatch.setattr(http_sources, "MAX_BYTES", 10)
    source.url = base + "/json"
    with pytest.raises(DataSourceError, match="sınır"):
        source.query({}, context())


@pytest.mark.parametrize("address", ["169.254.169.254", "::ffff:169.254.169.254", "fe80::1", "fd00:ec2::254", "0.0.0.0"])
def test_metadata_peers_are_blocked(address):
    with pytest.raises(DataSourceError):
        safe_peer(address)


def test_http_requires_explicit_opt_in_and_url_cannot_hold_secrets():
    for url in ("http://example.com", "https://user:password@example.com", "https://example.com?a=secret"):
        with pytest.raises(DataSourceError):
            validate_http_url(url)


def test_promql_variables_remain_quoted_and_cannot_be_inserted_as_syntax():
    variables = {"job":{"value":'x"} or up{job="other'}}
    expr = 'up{job=~"$job"}'
    templating.validate_promql_variables(expr, variables, {})
    prepared = templating.interpolate(expr, variables, default_format="promql", strict=True)
    assert '\\"' in prepared
    with pytest.raises(ValueError):
        templating.validate_promql_variables("up{$job}", variables, {})


def test_v1_to_v2_preserves_datasources_and_accepts_new_types(tmp_path):
    settings = replace(Settings.from_env(), data_dir=tmp_path, allow_loopback_datasources=True)
    with db.sqlite_store.connect(settings) as connection, db.transaction(connection):
        for statement in db.MIGRATIONS[1]:
            connection.execute(statement)
        connection.execute("INSERT INTO schema_versions VALUES (1,?)", (db.utcnow(),))
        db.sqlite_store.set_schema_version(connection, 1)
        connection.execute("""INSERT INTO datasources(id,uid,name,type,secure_json,created_at,updated_at,updated_by)
                        VALUES('keep','keep','Keep','testdata','ciphertext','test','test','test')""")
    db.init_db(settings)
    with db.connect(settings) as connection:
        assert connection.execute("SELECT secure_json FROM datasources WHERE uid='keep'").fetchone()[0] == "ciphertext"
        assert db.schema_version(connection) == db.CURRENT_VERSION
