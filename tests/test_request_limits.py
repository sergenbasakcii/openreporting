"""Exercise actual ASGI chunks and prove rejected bodies cannot reach mutations."""

import asyncio
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from openreporting.config import Settings
from openreporting.request_limits import RequestBodyLimitMiddleware
from openreporting.security import create_user
from openreporting.web import create_app


async def exchange(chunks, *, headers=(), limit=16):
    received, sent, invoked = [], [], []

    async def endpoint(scope, receive, send):
        invoked.append(True)
        received.append((await receive())["body"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    iterator = iter(chunks)

    async def receive():
        return next(iterator)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "headers": list(headers), "path": "/mutation"}
    await RequestBodyLimitMiddleware(endpoint, limit)(scope, receive, send)
    return received, sent, invoked


def chunk(body, more=False):
    return {"type": "http.request", "body": body, "more_body": more}


@pytest.mark.parametrize("headers", [(), ((b"transfer-encoding", b"chunked"),), ((b"content-length", b"1"),)])
def test_missing_chunked_and_understated_length_cannot_bypass_limit(headers):
    received, sent, invoked = asyncio.run(exchange([chunk(b"a" * 10, True), chunk(b"b" * 10)], headers=headers))
    assert not invoked and received == []
    assert sent[0]["status"] == 413
    assert b"aaaaaaaaaa" not in sent[1]["body"]


@pytest.mark.parametrize(
    "headers",
    [
        ((b"content-length", b"-1"),),
        ((b"content-length", b"abc"),),
        ((b"content-length", b"1"), (b"content-length", b"1")),
        ((b"content-length", b"1"), (b"transfer-encoding", b"chunked")),
    ],
)
def test_ambiguous_or_invalid_framing_is_rejected_before_body_read(headers):
    _, sent, invoked = asyncio.run(exchange([], headers=headers))
    assert not invoked and sent[0]["status"] == 400


def test_oversized_and_extremely_long_length_is_rejected_without_integer_overflow():
    for value in (b"17", b"9" * 5000):
        _, sent, invoked = asyncio.run(exchange([], headers=[(b"content-length", value)]))
        assert not invoked and sent[0]["status"] == 413


def test_small_chunks_are_replayed_once_at_boundary_and_mismatch_is_rejected():
    result = asyncio.run(exchange([chunk(b"a" * 8, True), chunk(b"b" * 8)], headers=[(b"content-length", b"16")]))
    assert result[0] == [b"a" * 8 + b"b" * 8] and result[1][0]["status"] == 204
    result = asyncio.run(exchange([chunk(b"a")], headers=[(b"content-length", b"2")]))
    assert not result[2] and result[1][0]["status"] == 400


def test_disconnected_upload_never_reaches_endpoint_and_requests_do_not_share_buffer():
    result = asyncio.run(exchange([chunk(b"a", True), {"type": "http.disconnect"}]))
    assert not result[1] and not result[2]

    async def concurrent():
        return await asyncio.gather(exchange([chunk(b"one")]), exchange([chunk(b"two")]))

    first, second = asyncio.run(concurrent())
    assert first[0] == [b"one"] and second[0] == [b"two"]


def test_application_rejects_large_stream_with_security_headers_and_keeps_login(tmp_path):
    settings = replace(
        Settings.from_env(),
        data_dir=tmp_path,
        database_url="",
        secure_cookie=False,
        secret_key_file="",
        ldap_enabled=False,
        mail_enabled=False,
        zabbix_url="",
        zabbix_token_file="",
    )
    app = create_app(settings)
    create_user(settings, "admin1", "isolated-body-limit-password", "admin")
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post("/api/login", content=iter([b"x" * 1_000_001, b"x" * 1_000_001]), headers={"Content-Type": "application/json"})
        assert response.status_code == 413 and response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"
        assert client.post("/api/login", json={"username": "admin1", "password": "isolated-body-limit-password"}).status_code == 200
