"""Executes panel queries: variables → datasources → functions → expressions → transformations.

Used by the HTTP API *and* the report worker, so a dashboard panel and its PDF
page are computed by the same code path.

``trusted=False`` is used for viewer-initiated requests: variable values are
then always formatted safely for the target datasource (``${var:raw}`` cannot
inject SQL) and datasource error details are replaced by generic messages.
"""
import copy
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import datasources
from .datasources.base import DataSourceError, QueryContext
from .domain import DomainError
from .expressions import evaluate
from .frames import total_points
from .series_functions import apply_functions, query_option
from .templating import builtin_variables, interpolate_deep
from .timerange import calculate_interval, parse_duration, resolve_range, zone
from .transformations import apply_transformations

log = logging.getLogger(__name__)
EXPRESSION_UID = "__expr__"
MAX_TARGETS = 26
SLOT_WAIT_S = 60
_slots = {}
_slots_lock = threading.Lock()


class QueryError(DomainError):
    pass


def _ds_ref(target, panel_ds):
    ref = target.get("datasource") or panel_ds
    if isinstance(ref, dict):
        return ref.get("uid") or ref.get("name")
    return ref


def is_expression(target, panel_ds=None):
    ref = target.get("datasource")
    if isinstance(ref, dict):
        return ref.get("type") == "__expr__" or ref.get("uid") == EXPRESSION_UID
    return ref == EXPRESSION_UID


def _slot(settings, uid):
    """Per-datasource concurrency limit shared by all requests of this process."""
    with _slots_lock:
        if uid not in _slots:
            _slots[uid] = threading.BoundedSemaphore(max(2, settings.query_concurrency * 2))
        return _slots[uid]


def local_midnight_ms(moment, tz):
    local = moment.astimezone(zone(tz))
    return int(local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


def build_context(settings, request, *, user=""):
    rng = request.get("range") or {}
    tz = request.get("timezone") or "UTC"
    now = None
    if request.get("now"):
        # One anchor per dashboard refresh keeps every panel on the same window.
        now = datetime.fromtimestamp(int(request["now"]) / 1000, timezone.utc)
        if abs((now - datetime.now(timezone.utc)).total_seconds()) > 300:
            now = None
    start, end = resolve_range(rng.get("from", "now-6h"), rng.get("to", "now"), tz, now=now)
    max_points = int(request.get("maxDataPoints") or 1000)
    if not 10 <= max_points <= 20000:
        raise QueryError("maxDataPoints must be 10..20000")
    interval_s = calculate_interval(start, end, max_points, request.get("minInterval") or None)
    variables = request.get("variables") or {}
    builtins = builtin_variables(start, end, interval_s, dashboard=str(request.get("dashboardTitle", "")),
                                 user=user, timezone_name=tz)
    return QueryContext(start=start, end=end, interval_s=interval_s, max_points=max_points, timezone=tz,
                        anchor_ms=local_midnight_ms(start, tz), variables=variables, builtins=builtins, user=user,
                        max_series_points=settings.max_series_points)


def _run_target(settings, target, ctx, panel_ds, transport, trusted):
    uid = _ds_ref(target, panel_ds)
    ds = datasources.get(settings, uid, transport=transport)
    prepared = interpolate_deep(copy.deepcopy(target), ctx.variables, default_format=ds.default_format,
                                builtins=ctx.builtins, strict=not trusted)
    local_ctx = ctx
    min_interval = prepared.get("interval") or ds.options.get("time_interval")
    if min_interval:
        local_ctx = QueryContext(**{**local_ctx.__dict__,
                                    "interval_s": calculate_interval(ctx.start, ctx.end, ctx.max_points, min_interval)})
    shift = query_option(prepared.get("functions"), "timeShift")
    offset_ms = int(parse_duration(shift) * 1000) if shift else 0
    if offset_ms:
        # timeShift for every datasource: query the earlier window, then move points forward.
        delta = timedelta(milliseconds=offset_ms)
        local_ctx = QueryContext(**{**local_ctx.__dict__, "start": local_ctx.start - delta, "end": local_ctx.end - delta,
                                    "anchor_ms": local_ctx.anchor_ms - offset_ms})
    slot = _slot(settings, ds.uid)
    if not slot.acquire(timeout=SLOT_WAIT_S):
        raise QueryError("Veri kaynağı meşgul; birazdan tekrar deneyin")
    try:
        result = ds.query(prepared, local_ctx)
    finally:
        slot.release()
    frames = result.frames
    if offset_ms:
        frames = [dict(f, points=[[t + offset_ms, v] for t, v in f["points"]]) if f["type"] == "timeseries" else f
                  for f in frames]
    frames = apply_functions(frames, prepared.get("functions"), local_ctx.interval_ms, ctx.anchor_ms)
    ref_id = target.get("refId", "A")
    for frame in frames:
        frame["refId"] = ref_id
        frame.setdefault("meta", {})["datasource"] = ds.name
    return frames, result.warnings, {**result.meta, "datasource": ds.name, "type": ds.type}


def _public_error(exc, trusted):
    """Datasource errors may carry hosts, relations or SQL fragments; viewers get a generic text."""
    if trusted or not isinstance(exc, DataSourceError):
        return str(exc)
    return "Sorgu çalıştırılamadı; ayrıntılar için yöneticinize başvurun"


def run(settings, request, *, user="", transport=None, trusted=True):
    targets = [t for t in (request.get("targets") or []) if isinstance(t, dict)]
    if not targets:
        raise QueryError("At least one query is required")
    if len(targets) > MAX_TARGETS:
        raise QueryError(f"A panel may contain at most {MAX_TARGETS} queries")
    ctx = build_context(settings, request, user=user)
    panel_ds = request.get("datasource")
    ref_ids = [t.get("refId") or chr(65 + i) for i, t in enumerate(targets)]
    if len(set(ref_ids)) != len(ref_ids):
        raise QueryError("Query refIds must be unique")
    for target, ref_id in zip(targets, ref_ids):
        target["refId"] = ref_id
    results = {}
    outputs = {}
    plain = [t for t in targets if not is_expression(t, panel_ds)]
    expressions = [t for t in targets if is_expression(t, panel_ds)]

    def execute(target):
        try:
            return target["refId"], _run_target(settings, target, ctx, panel_ds, transport, trusted), None
        except (DomainError, ValueError) as exc:
            if not trusted:
                log.warning("Query %s failed for %s: %s", target.get("refId"), user or "-", exc)
            return target["refId"], None, _public_error(exc, trusted)
        except Exception as exc:  # noqa: BLE001 - never leak a stack trace to the browser
            log.exception("Query %s failed", target.get("refId"))
            return target["refId"], None, f"Sorgu başarısız: {type(exc).__name__}"

    workers = max(1, min(settings.query_concurrency, len(plain)))
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="openreporting-query") as pool:
            executed = list(pool.map(execute, plain))
    else:
        executed = [execute(t) for t in plain]
    for ref_id, payload, error in executed:
        if error:
            results[ref_id] = {"error": error, "warnings": [], "meta": {}}
            outputs[ref_id] = []
            continue
        frames, warnings, meta = payload
        outputs[ref_id] = frames
        results[ref_id] = {"error": None, "warnings": warnings, "meta": meta}
    end_ms = int(ctx.end.timestamp() * 1000)
    for target in expressions:
        ref_id = target["refId"]
        model = target.get("model") if isinstance(target.get("model"), dict) else target
        try:
            frames, warnings = evaluate({**model, "refId": ref_id}, outputs, ctx.interval_ms, end_ms, ctx.anchor_ms)
            outputs[ref_id] = frames
            results[ref_id] = {"error": None, "warnings": warnings, "meta": {"type": "expression"}}
        except (DomainError, ValueError) as exc:
            outputs[ref_id] = []
            results[ref_id] = {"error": str(exc), "warnings": [], "meta": {}}
        except Exception as exc:  # noqa: BLE001 - one bad expression must not fail the panel
            log.exception("Expression %s failed", ref_id)
            outputs[ref_id] = []
            results[ref_id] = {"error": f"İfade hesaplanamadı: {type(exc).__name__}", "warnings": [], "meta": {}}
    visible = [f for t in targets if not t.get("hide") for f in outputs.get(t["refId"], [])]
    if total_points(visible) > settings.max_series_points:
        raise QueryError("Sonuç nokta bütçesini aşıyor; aralığı daraltın veya groupBy/aggregateBy kullanın")
    transform_error = None
    try:
        frames = apply_transformations(visible, request.get("transformations"))
    except (DomainError, ValueError, TypeError, IndexError, KeyError) as exc:
        log.warning("Transformation failed: %s", exc)
        frames, transform_error = visible, str(exc) if isinstance(exc, DomainError) else "Dönüşüm uygulanamadı"
    return {"frames": frames, "results": results, "transformError": transform_error,
            "request": {"from": int(ctx.start.timestamp() * 1000), "to": end_ms,
                        "intervalMs": ctx.interval_ms, "maxDataPoints": ctx.max_points}}


def metric_find(settings, uid, query, request=None, *, user="", transport=None, trusted=True):
    ds = datasources.get(settings, uid, transport=transport)
    ctx = build_context(settings, request or {"range": {"from": "now-6h", "to": "now"}}, user=user)
    prepared = interpolate_deep(copy.deepcopy(query), ctx.variables, default_format=ds.default_format,
                                builtins=ctx.builtins, strict=not trusted)
    slot = _slot(settings, ds.uid)
    if not slot.acquire(timeout=SLOT_WAIT_S):
        raise QueryError("Veri kaynağı meşgul; birazdan tekrar deneyin")
    try:
        return ds.metric_find(prepared, ctx)
    except DataSourceError as exc:
        if trusted:
            raise
        log.warning("metric_find failed for %s: %s", user or "-", exc)
        raise DataSourceError(_public_error(exc, trusted)) from exc
    finally:
        slot.release()
