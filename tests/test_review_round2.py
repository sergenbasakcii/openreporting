"""Regression tests for the second review round (PR #1)."""

import pytest

from openreporting.datasources import validate as validate_datasource
from openreporting.datasources.base import DataSourceError
from openreporting.datasources.http_sources import _numeric, safe_peer
from openreporting.db import connect, transaction
from openreporting.reporting import service
from openreporting.templating import validate_promql_variables
from tests.test_reporting import env  # noqa: F401 - pytest fixture

VARS = {"inst": {"value": "x"}}


@pytest.mark.parametrize(
    "query",
    [
        'up{job=`x"`, instance=~$inst, z="a"}',  # a quote inside a raw string must not "open" a string
        "up{job='$inst'}",  # single quotes are not escaped by the promql format
        'up{i="$inst}',  # unterminated string
        "rate(x[5m]) or $inst",
    ],
)
def test_promql_variables_rejected_outside_double_quotes(query):
    with pytest.raises(ValueError):
        validate_promql_variables(query, VARS, {})


@pytest.mark.parametrize("query", ['up{instance=~"$inst"}', 'up{job="a\\"b", i="$inst"}', 'up{job=`raw`, i="$inst"}'])
def test_promql_variables_allowed_inside_double_quotes(query):
    validate_promql_variables(query, VARS, {})


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "::1", "::ffff:127.0.0.1", "64:ff9b::7f00:1", "2002:7f00:1::", "169.254.169.254", "100.100.100.200", "168.63.129.16", "fd00:ec2::254"],
)
def test_http_sources_block_loopback_metadata_and_embedded_ipv4(address):
    with pytest.raises(DataSourceError):
        safe_peer(address)


def test_http_sources_allow_private_networks_and_opt_in_loopback():
    assert safe_peer("10.20.30.40") and safe_peer("192.168.1.10") and safe_peer("fd12::1")
    assert safe_peer("127.0.0.1", allow_loopback=True)


def test_identifier_strings_stay_text():
    assert [_numeric(v) for v in ("007", "0532123", "1e3", "", True)] == [False] * 5
    assert all(_numeric(v) for v in ("0", "12", "-0.5", "3.14", 7, 2.5))


def test_non_numeric_datasource_option_is_a_validation_error(env):  # noqa: F811
    settings, _, _ = env
    with pytest.raises(DataSourceError):
        validate_datasource("prometheus", "https://prom.example.com", {"timeout": "fast"}, settings)


def test_interrupted_mail_keeps_finished_report_downloadable(env):  # noqa: F811
    settings, _, user = env
    created = service.save_report(
        settings, user, {"name": "Teslim", "dashboard_uid": "rep-test", "time_range": {"from": "now-6h", "to": "now"}, "formats": ["pdf"]}
    )
    finished = service.request_run(settings, user, created["id"], {})["run_id"]
    service.execute(settings, service.claim(settings))
    unfinished = service.request_run(settings, user, created["id"], {"time_range": {"from": "now-2h", "to": "now"}})["run_id"]
    service.claim(settings)
    with connect(settings) as db, transaction(db):
        db.execute("UPDATE dash_report_runs SET delivery_status='sending' WHERE id=?", (finished,))
    service.mark_interrupted(settings, force=True)
    runs = {r["id"]: r for r in service.list_runs(settings, created["id"])}
    assert runs[finished]["status"] == "completed" and runs[finished]["delivery_status"] == "unknown"
    assert runs[unfinished]["status"] == "needs_review"
    path, _ = service.verified_file(settings, finished, "pdf", user)
    assert path.read_bytes().startswith(b"%PDF")
