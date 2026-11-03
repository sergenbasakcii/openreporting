"""Regressions from the third full review (backend correctness)."""

from dataclasses import replace

import pytest

from openreporting import dashboards, security
from openreporting.config import Settings
from openreporting.datasources.postgres import PostgresDataSource
from openreporting.db import init_db
from openreporting.frames import ts_frame
from openreporting.series_functions import apply_functions
from openreporting.units import resolve_unit


def test_rate_after_a_gap_uses_the_last_valid_sample():
    frames = [ts_frame("x", [[0, 10.0], [60_000, None], [120_000, 70.0]], ref_id="A")]
    out = apply_functions(frames, [{"name": "rate", "params": []}], 60_000)
    assert out[0]["points"] == [[0, None], [60_000, None], [120_000, 0.5]]


@pytest.mark.parametrize("raw", ["m", "h", "d"])
def test_ambiguous_zabbix_units_are_not_read_as_time(raw):
    assert resolve_unit(None, raw) == f"suffix: {raw}"


def test_sql_history_last_first_median_are_not_averages():
    modes = PostgresDataSource.HISTORY_MODES
    assert "ORDER BY clock DESC" in modes["history_last"] and "ORDER BY clock ASC" in modes["history_first"]
    assert modes["history_median"].startswith("PERCENTILE_CONT(0.5)")


def test_malformed_dashboard_version_is_a_client_error(tmp_path):
    settings = replace(Settings.from_env(), data_dir=tmp_path / "data", database_url="", secret_key_file="")
    init_db(settings)
    user = {"id": security.create_user(settings, "versioner", "a-long-enough-password", "editor"), "role": "editor"}
    saved = dashboards.save(settings, user, {"title": "Versioned"})
    with pytest.raises(dashboards.DashboardError, match="sürüm"):
        dashboards.save(settings, user, {"uid": saved["uid"], "title": "Versioned", "version": "abc"})
