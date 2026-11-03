"""Time math, units, series functions, expressions, transformations, templating."""

from datetime import datetime, timezone

import pytest

from openreporting import timerange, units
from openreporting.expressions import ExpressionError, compile_math, evaluate, evaluate_math
from openreporting.frames import reduce_values, ts_frame
from openreporting.series_functions import FunctionError, apply_functions, normalize, query_option
from openreporting.templating import ALL, builtin_variables, interpolate, interpolate_deep
from openreporting.transformations import apply_transformations

NOW = datetime(2026, 10, 24, 10, 30, 15, tzinfo=timezone.utc)  # 13:30 in Istanbul


def test_relative_time_math_and_calendar_rounding():
    assert timerange.parse("now-6h", now=NOW) == datetime(2026, 10, 24, 4, 30, 15, tzinfo=timezone.utc)
    start = timerange.parse("now/d", now=NOW, tz="Europe/Istanbul")
    end = timerange.parse("now/d", round_up=True, now=NOW, tz="Europe/Istanbul")
    assert start == datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc)
    assert end.isoformat().startswith("2026-10-24T20:59:59.999")
    month_start = timerange.parse("now-1M/M", now=NOW, tz="UTC")
    assert month_start == datetime(2026, 9, 1, tzinfo=timezone.utc)
    week = timerange.parse("now/w", now=NOW, tz="UTC")
    assert week.weekday() == 0 and week.hour == 0


def test_absolute_and_epoch_values_and_errors():
    assert timerange.parse("1770000000000") == datetime.fromtimestamp(1770000000, timezone.utc)
    assert timerange.parse("2026-10-01T00:00:00Z").year == 2026
    with pytest.raises(timerange.TimeRangeError):
        timerange.parse("now-6x")
    with pytest.raises(timerange.TimeRangeError):
        timerange.resolve_range("now", "now-1h", now=NOW)


def test_interval_calculation_rounds_to_nice_values():
    start, end = timerange.resolve_range("now-24h", "now", now=NOW)
    assert timerange.calculate_interval(start, end, 1000) == 60
    assert timerange.calculate_interval(start, end, 1000, "5m") == 300
    assert timerange.parse_duration("1d") == 86400
    assert timerange.format_duration(300) == "5m"


def test_unit_formatting():
    assert units.format_value(1_500_000, "bps") == "1.5 Mbps"
    assert units.format_value(1536, "bytes") == "1.5 KiB"
    assert units.format_value(42.123, "percent", 1) == "42.1%"
    assert units.format_value(0.5, "percentunit") == "50%"
    assert units.format_value(None, "percent") == "Veri yok"
    assert units.format_value(90061, "dtdurations") == "1 gün 1 sa"
    assert units.format_value(0.0021, "s") == "2.1 ms"
    assert units.resolve_unit("auto", "bps") == "bps"
    assert units.resolve_unit(None, "pkts") == "suffix: pkts"
    assert units.format_value(5, "suffix: pkts") == "5 pkts"


def series(name, values, host=None, step=60_000, start=0, unit=""):
    labels = {"host": host} if host else {}
    return ts_frame(name, [[start + i * step, v] for i, v in enumerate(values)], labels=labels, unit=unit, ref_id="A")


def test_reducers_never_invent_values():
    assert reduce_values([None, None], "mean") is None
    assert reduce_values([1, None, 3], "mean") == 2
    assert reduce_values([1, None, 3], "lastNotNull") == 3
    assert reduce_values([1, None, 3], "last") == 3
    assert reduce_values([5, 7, 2, 4], "delta") == 2 + 2 + 2  # reset: count from 0
    assert reduce_values(list(range(101)), "p95") == pytest.approx(95)


def test_group_functions_aggregate_and_alias():
    frames = [series("a", [1, 2, 3, None], host="h1"), series("b", [3, 4, 5, 6], host="h2")]
    out = apply_functions(frames, [{"def": {"name": "aggregateBy"}, "params": ["1m", "avg"]}], 60_000)
    assert len(out) == 1
    assert [p[1] for p in out[0]["points"]] == [2, 3, 4, 6]
    assert out[0]["meta"]["coverage"][-1] == [180_000, 1]
    top = apply_functions(frames, [{"name": "top", "params": [1, "max"]}], 60_000)
    assert [f["name"] for f in top] == ["b"]
    aliased = apply_functions(frames, [{"name": "setAlias", "params": ["{{host}} CPU"]}], 60_000)
    assert [f["name"] for f in aliased] == ["h1 CPU", "h2 CPU"]
    scaled = apply_functions(frames, [{"name": "scale", "params": [8]}], 60_000)
    assert scaled[0]["points"][0][1] == 8 and scaled[0]["points"][3][1] is None
    grouped = apply_functions([series("a", [1, 3, 5, 7])], [{"name": "groupBy", "params": ["2m", "max"]}], 60_000)
    assert [p[1] for p in grouped[0]["points"]] == [3, 7]
    filtered = apply_functions(frames, [{"name": "filterSeries", "params": ["max", ">", 5]}], 60_000)
    assert [f["name"] for f in filtered] == ["b"]
    assert query_option([{"name": "timeShift", "params": ["1d"]}], "timeShift") == "1d"
    with pytest.raises(FunctionError):
        normalize({"name": "rm -rf"})


def test_rate_marks_counter_reset_as_missing():
    frame = series("c", [100, 160, 10, 70])
    out = apply_functions([frame], [{"name": "rate"}], 60_000)
    assert [p[1] for p in out[0]["points"]] == [None, 1.0, None, 1.0]


def test_math_expression_safe_and_label_matched():
    a = [series("in", [10, 20], host="h1"), series("in", [1, 2], host="h2")]
    b = [series("out", [5, 5], host="h2"), series("out", [10, 10], host="h1")]
    frames, warnings = evaluate_math("$A / $B * 100", {"A": a, "B": b}, 60_000, "C")
    assert not warnings
    by_host = {f["labels"]["host"]: [p[1] for p in f["points"]] for f in frames}
    assert by_host == {"h1": [100, 200], "h2": [20, 40]}
    zero, _ = evaluate_math("$A / 0", {"A": a[:1]}, 60_000, "C")
    assert zero[0]["points"][0][1] is None
    for bad in ("__import__('os')", "$A.__class__", "open('x')", "[1,2]"):
        with pytest.raises(ExpressionError):
            compile_math(bad)
    reduced, _ = evaluate({"type": "reduce", "expression": "A", "reducer": "max", "refId": "R"}, {"A": a}, 60_000, 999)
    assert reduced[0]["points"] == [[999, 20]]


def test_transformations_group_matrix_and_summary():
    frames = []
    for host, cpu, mem in (("h1", [10, 30], [50, 50]), ("h2", [70, 90], [20, 40])):
        c = series(f"{host}: CPU", cpu, host=host, unit="%")
        c["labels"]["item"] = "CPU"
        m = series(f"{host}: Mem", mem, host=host, unit="%")
        m["labels"]["item"] = "Memory"
        frames += [c, m]
    matrix = apply_transformations(frames, [{"id": "reduceByLabel", "options": {"label": "host", "reducer": "mean"}}])
    table = matrix[0]
    assert [c["name"] for c in table["columns"]] == ["host", "CPU", "Memory"]
    assert table["rows"] == [["h1", 20, 50], ["h2", 80, 30]]
    summary = apply_transformations(
        frames,
        [
            {"id": "reduce", "options": {"reducers": ["max", "mean"]}},
            {"id": "sortBy", "options": {"sort": [{"field": "En yüksek", "desc": True}]}},
            {"id": "limit", "options": {"limitField": 2}},
        ],
    )
    assert len(summary[0]["rows"]) == 2 and summary[0]["rows"][0][0] == "h2: CPU"
    joined = apply_transformations(frames[:2], [{"id": "seriesToColumns"}])
    assert joined[0]["columns"][0]["type"] == "time" and len(joined[0]["rows"]) == 2
    calc = apply_transformations(matrix, [{"id": "calculateField", "options": {"mode": "reduceRow", "alias": "Toplam", "reduce": {"reducer": "sum"}}}])
    assert calc[0]["rows"][0][-1] == 70


def test_variable_interpolation_formats():
    variables = {
        "host": {"value": ["a.b", "c"], "multi": True, "options": []},
        "group": {"value": ALL, "includeAll": True, "options": [{"text": "x", "value": "x"}, {"text": "y", "value": "y"}]},
        "name": {"value": "O'Brien"},
    }
    assert interpolate("$host", variables, default_format="zabbix") == "/^(?:a\\.b|c)$/"
    assert interpolate("${host:csv}", variables) == "a.b,c"
    assert interpolate("[[host:pipe]]", variables) == "a.b|c"
    assert interpolate("${group:sqlstring}", variables) == "'x','y'"
    assert interpolate("WHERE n = $name", variables, default_format="sqlstring") == "WHERE n = 'O''Brien'"
    assert interpolate("$unknown stays", variables) == "$unknown stays"
    builtins = builtin_variables(NOW, NOW.replace(hour=11), 60)
    assert interpolate("$__interval / $__range", {}, builtins=builtins) == "1m / 1h"
    deep = interpolate_deep({"refId": "$host", "host": {"filter": "$host"}}, variables, default_format="zabbix")
    assert deep["refId"] == "$host" and deep["host"]["filter"].startswith("/^")
