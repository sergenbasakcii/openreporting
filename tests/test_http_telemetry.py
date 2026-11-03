import asyncio
from dataclasses import replace
import json
import logging
import re

from fastapi.testclient import TestClient
import pytest

from openreporting.config import Settings
from openreporting.http_telemetry import HttpMetrics, HttpTelemetryMiddleware
from openreporting.web import create_app


@pytest.fixture
def client(tmp_path):
    settings = replace(
        Settings.from_env(),
        data_dir=tmp_path,
        database_url="",
        secret_key_file="",
        secure_cookie=False,
        ldap_enabled=False,
        mail_enabled=False,
        zabbix_url="",
        zabbix_token_file="",
    )
    app = create_app(settings)

    @app.get("/_fault/{private_value}")
    def fault(private_value):
        raise RuntimeError("secret-exception-credential-" + private_value)

    app.router.routes.insert(0, app.router.routes.pop())

    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 12345)) as http:
        yield http


def test_server_generated_ids_and_logs_never_copy_request_contents(client, caplog):
    caplog.set_level(logging.INFO, logger="openreporting.http")
    first = client.get(
        "/api/dashboards/uid/private-title?token=secret-query",
        headers={"X-Request-ID": "secret-client-id", "Authorization": "secret-auth", "Cookie": "secret-cookie"},
    )
    second = client.post("/api/login", json={"username": "unknown", "password": "secret-login-password"})
    assert re.fullmatch("[a-f0-9]{32}", first.headers["x-request-id"])
    assert second.headers["x-request-id"] != first.headers["x-request-id"]
    events = [json.loads(r.message) for r in caplog.records if r.name == "openreporting.http"]
    assert events[0]["route"] == "/api/dashboards/uid/{uid}"
    assert events[0]["request_id"] == first.headers["x-request-id"]
    assert events[0]["duration_ms"] >= 0 and events[0]["complete"] is True
    encoded = json.dumps(events)
    assert "secret-" not in encoded and "private-title" not in encoded and "unknown" not in encoded


def test_unhandled_error_has_safe_body_headers_and_correlated_log(client, caplog):
    caplog.set_level(logging.INFO, logger="openreporting.http")
    response = client.get("/_fault/private-secret")
    assert response.status_code == 500 and response.json() == {"detail": "Internal server error"}
    assert response.headers["x-frame-options"] == "DENY"
    event = json.loads(next(r.message for r in caplog.records if r.name == "openreporting.http"))
    assert event["status"] == 500 and event["route"] == "/_fault/{private_value}"
    assert event["request_id"] == response.headers["x-request-id"]
    assert "private-secret" not in caplog.text and "secret-exception" not in caplog.text


def test_rejections_are_correlated_and_metrics_have_bounded_labels(client):
    for i in range(15):
        response = client.get("/private-identifier-" + str(i))
        assert response.status_code == 404 and response.headers["x-request-id"]
    host = client.get("/healthz", headers={"Host": "hostile.example"})
    assert host.status_code == 400 and host.headers["x-request-id"]
    origin = client.post("/api/login", json={}, headers={"Origin": "https://hostile.example"})
    assert origin.status_code == 403 and origin.headers["x-request-id"]
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    worker = client.app.state.http_metrics.worker_id
    assert f'openreporting_http_requests_total{{worker_id="{worker}",method="GET",status_class="4xx"}} 16' in metrics.text
    assert f'openreporting_http_duration_seconds_count{{worker_id="{worker}"}} 17' in metrics.text
    assert "private-identifier" not in metrics.text and "hostile" not in metrics.text and "request_id" not in metrics.text
    assert client.get("/metrics", headers={"Host": "localhost"}).status_code == 200


def test_metrics_are_not_available_to_remote_clients(client):
    app = client.app
    with TestClient(app, base_url="http://localhost", client=("192.0.2.1", 12345)) as remote:
        assert remote.get("/metrics").status_code == 404


def test_incomplete_response_releases_inflight_and_counts_failure():
    metrics = HttpMetrics()

    async def failed(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"partial", "more_body": True})
        raise RuntimeError("stream failed")

    async def send(message):
        pass

    async def receive():
        return {"type": "http.disconnect"}

    async def run():
        await HttpTelemetryMiddleware(failed, metrics)({"type": "http", "method": "UNBOUNDED-METHOD", "path": "/dynamic"}, receive, send)

    with pytest.raises(RuntimeError):
        asyncio.run(run())
    assert metrics.inflight == 0 and metrics.incomplete == 1
    assert len(metrics.counts) == 1 and ("OTHER", "2xx") in metrics.counts
