"""Query post-processing functions (Grafana Zabbix-plugin compatible names).

Every query, whatever its datasource, can carry ``functions``. They run on the
server, so the dashboard view and the scheduled PDF are calculated identically.
"""

import math
import re
from collections import defaultdict

from .domain import DomainError
from .frames import finite, reduce_values, ts_frame
from .safe_regex import RegexError, compile_slashed
from .timerange import parse_duration

AGG_FUNCS = ("avg", "min", "max", "sum", "count", "median", "first", "last")

CATALOG = [
    {
        "name": "groupBy",
        "category": "Dönüşüm",
        "params": [{"name": "aralık", "type": "interval", "default": "1h"}, {"name": "fonksiyon", "type": "agg", "default": "avg"}],
        "description": "Her seriyi verilen zaman aralığında toplulaştırır.",
    },
    {
        "name": "scale",
        "category": "Dönüşüm",
        "params": [{"name": "çarpan", "type": "number", "default": 100}],
        "description": "Değerleri sabit ile çarpar (ör. bayt → bit için 8).",
    },
    {"name": "offset", "category": "Dönüşüm", "params": [{"name": "ekle", "type": "number", "default": 0}], "description": "Değerlere sabit ekler."},
    {"name": "delta", "category": "Dönüşüm", "params": [], "description": "Ardışık noktalar arası fark."},
    {"name": "rate", "category": "Dönüşüm", "params": [], "description": "Saniye başına değişim (sayaç sıfırlanmasında nokta boş bırakılır)."},
    {"name": "movingAverage", "category": "Dönüşüm", "params": [{"name": "nokta", "type": "int", "default": 5}], "description": "Kayan ortalama."},
    {
        "name": "exponentialMovingAverage",
        "category": "Dönüşüm",
        "params": [{"name": "nokta", "type": "int", "default": 10}],
        "description": "Üssel kayan ortalama.",
    },
    {
        "name": "percentile",
        "category": "Dönüşüm",
        "params": [{"name": "aralık", "type": "interval", "default": "1h"}, {"name": "yüzdelik", "type": "number", "default": 95}],
        "description": "Aralık başına yüzdelik değer.",
    },
    {
        "name": "removeAboveValue",
        "category": "Dönüşüm",
        "params": [{"name": "eşik", "type": "number", "default": 0}],
        "description": "Eşiğin üstündeki değerleri boş yapar.",
    },
    {
        "name": "removeBelowValue",
        "category": "Dönüşüm",
        "params": [{"name": "eşik", "type": "number", "default": 0}],
        "description": "Eşiğin altındaki değerleri boş yapar.",
    },
    {
        "name": "transformNull",
        "category": "Dönüşüm",
        "params": [{"name": "değer", "type": "number", "default": 0}],
        "description": "Boş noktaları açıkça verilen değerle doldurur (varsayılan davranış değildir).",
    },
    {"name": "absolute", "category": "Dönüşüm", "params": [], "description": "Mutlak değer."},
    {
        "name": "aggregateBy",
        "category": "Toplulaştırma",
        "params": [{"name": "aralık", "type": "interval", "default": "1h"}, {"name": "fonksiyon", "type": "agg", "default": "avg"}],
        "description": "Tüm serileri (ör. gruptaki tüm hostları) tek seride birleştirir.",
    },
    {"name": "sumSeries", "category": "Toplulaştırma", "params": [], "description": "Tüm serilerin zaman kovası bazında toplamı."},
    {"name": "averageSeries", "category": "Toplulaştırma", "params": [], "description": "Tüm serilerin zaman kovası bazında ortalaması."},
    {"name": "maxSeries", "category": "Toplulaştırma", "params": [], "description": "Kova bazında en yüksek seri değeri."},
    {"name": "minSeries", "category": "Toplulaştırma", "params": [], "description": "Kova bazında en düşük seri değeri."},
    {
        "name": "percentileAgg",
        "category": "Toplulaştırma",
        "params": [{"name": "aralık", "type": "interval", "default": "1h"}, {"name": "yüzdelik", "type": "number", "default": 95}],
        "description": "Tüm serilerin kova bazında yüzdelik değeri.",
    },
    {
        "name": "groupByLabel",
        "category": "Toplulaştırma",
        "params": [{"name": "etiket", "type": "string", "default": "group"}, {"name": "fonksiyon", "type": "agg", "default": "avg"}],
        "description": "Serileri etikete göre (ör. host grubu) birleştirir.",
    },
    {
        "name": "top",
        "category": "Filtre",
        "params": [{"name": "adet", "type": "int", "default": 5}, {"name": "ölçüt", "type": "reducer", "default": "mean"}],
        "description": "Seçilen ölçüte göre en yüksek N seri.",
    },
    {
        "name": "bottom",
        "category": "Filtre",
        "params": [{"name": "adet", "type": "int", "default": 5}, {"name": "ölçüt", "type": "reducer", "default": "mean"}],
        "description": "Seçilen ölçüte göre en düşük N seri.",
    },
    {
        "name": "sortSeries",
        "category": "Filtre",
        "params": [{"name": "yön", "type": "order", "default": "desc"}],
        "description": "Serileri ortalamaya göre sıralar.",
    },
    {
        "name": "filterSeries",
        "category": "Filtre",
        "params": [
            {"name": "ölçüt", "type": "reducer", "default": "max"},
            {"name": "operatör", "type": "op", "default": ">"},
            {"name": "eşik", "type": "number", "default": 0},
        ],
        "description": "Koşulu sağlamayan serileri çıkarır (ör. max > 80).",
    },
    {
        "name": "setAlias",
        "category": "Takma ad",
        "params": [{"name": "ad", "type": "string", "default": "{{host}}"}],
        "description": "Seri adını belirler: {{host}}, {{item}}, {{key}}, {{group}}, $__zbx_host_name ...",
    },
    {
        "name": "replaceAlias",
        "category": "Takma ad",
        "params": [{"name": "regex", "type": "string", "default": "/(.*)/"}, {"name": "yeni", "type": "string", "default": "$1"}],
        "description": "Seri adında düzenli ifadeyle değiştirme.",
    },
    {
        "name": "setAliasByRegex",
        "category": "Takma ad",
        "params": [{"name": "regex", "type": "string", "default": "(.*)"}],
        "description": "Seri adını regex eşleşmesinden üretir.",
    },
    {
        "name": "timeShift",
        "category": "Zaman",
        "params": [{"name": "kayma", "type": "interval", "default": "24h"}],
        "description": "Sorguyu geçmişe kaydırıp bugüne hizalar (dün/bugün karşılaştırması).",
    },
    {
        "name": "trendValue",
        "category": "Özel",
        "params": [{"name": "değer", "type": "trend", "default": "avg"}],
        "description": "Zabbix trend sorgusunda avg/min/max sütununu seçer.",
    },
    {
        "name": "consolidateBy",
        "category": "Özel",
        "params": [{"name": "fonksiyon", "type": "agg", "default": "avg"}],
        "description": "Noktalar seyreltilirken kullanılacak fonksiyon.",
    },
]
CATALOG_BY_NAME = {f["name"]: f for f in CATALOG}
# Applied by the datasource or query engine rather than as a post-step.
QUERY_LEVEL = frozenset({"timeShift", "trendValue", "consolidateBy"})


class FunctionError(DomainError):
    pass


def normalize(spec):
    """Accept ``{"name":..}``, Grafana-Zabbix ``{"def":{"name":..}}`` and older forms."""
    if isinstance(spec, str):
        return {"name": spec, "params": []}
    if not isinstance(spec, dict):
        raise FunctionError("Invalid function definition")
    name = spec.get("name")
    definition = spec.get("def")
    if not name and isinstance(definition, dict):
        name = definition.get("name")
    elif not name and isinstance(definition, str):
        name = definition
    if name not in CATALOG_BY_NAME:
        raise FunctionError(f"Unknown function: {name}")
    params = spec.get("params") or []
    if not isinstance(params, list) or len(params) > 4:
        raise FunctionError(f"Invalid parameters for {name}")
    return {"name": name, "params": params}


def _param(fn, index):
    params = fn["params"]
    if index < len(params) and params[index] not in (None, ""):
        return params[index]
    return CATALOG_BY_NAME[fn["name"]]["params"][index]["default"]


def _number(value, label="value"):
    number = finite(value)
    if number is None:
        raise FunctionError(f"Invalid numeric {label}")
    return number


def _agg(values, method):
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    if method == "avg":
        return sum(clean) / len(clean)
    if method in ("min", "max", "sum", "count", "median"):
        return reduce_values(clean, {"avg": "mean"}.get(method, method))
    if method == "first":
        return clean[0]
    if method == "last":
        return clean[-1]
    raise FunctionError(f"Unknown aggregation: {method}")


MAX_WINDOW = 1000


def bucket_key(ts, interval_ms, anchor_ms=0):
    """Bucket start for ``ts``; ``anchor_ms`` is a local midnight so daily buckets follow the dashboard zone."""
    return int(anchor_ms + (ts - anchor_ms) // interval_ms * interval_ms)


def bucketize(points, interval_ms, method="avg", anchor_ms=0):
    if interval_ms <= 0:
        return points
    buckets = defaultdict(list)
    order = []
    for ts, value in points:
        key = bucket_key(ts, interval_ms, anchor_ms)
        if key not in buckets:
            order.append(key)
        buckets[key].append(value)
    return [[key, _agg(buckets[key], method)] for key in sorted(order)]


def _combine(frames, interval_ms, method, name, anchor_ms=0):
    buckets = defaultdict(list)
    for frame in frames:
        for ts, value in bucketize(frame["points"], interval_ms, "avg", anchor_ms):
            if value is not None:
                buckets[ts].append(value)
    points = [[ts, _agg(values, method) if method != "percentile" else None] for ts, values in sorted(buckets.items())]
    units = {f.get("unit", "") for f in frames}
    labels = _common_labels(frames)
    meta = {"aggregated_series": len(frames), "coverage": [[ts, len(values)] for ts, values in sorted(buckets.items())]}
    return ts_frame(name, points, labels=labels, unit=units.pop() if len(units) == 1 else "", ref_id=frames[0].get("refId", "") if frames else "", meta=meta)


def _common_labels(frames):
    if not frames:
        return {}
    common = dict(frames[0].get("labels") or {})
    for frame in frames[1:]:
        labels = frame.get("labels") or {}
        common = {k: v for k, v in common.items() if labels.get(k) == v}
    return common


def _regex(text):
    try:
        return compile_slashed(text)
    except RegexError as exc:
        raise FunctionError(str(exc)) from exc


def alias(template, frame):
    labels = frame.get("labels") or {}
    values = {
        "$__zbx_host_name": labels.get("host", ""),
        "$__zbx_host": labels.get("host_technical", labels.get("host", "")),
        "$__zbx_item_name": labels.get("item", ""),
        "$__zbx_item_key": labels.get("item_key", ""),
        "$__zbx_item": labels.get("item", ""),
    }
    text = str(template)
    for key in sorted(values, key=len, reverse=True):
        text = text.replace(key, str(values[key]))
    text = re.sub(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}", lambda m: str(labels.get(m.group(1), frame.get("name", "") if m.group(1) == "name" else "")), text)
    return text


def _select(frames, fn, reverse):
    count = int(_number(_param(fn, 0), "count"))
    calc = _param(fn, 1)
    if calc == "avg":
        calc = "mean"
    scored = [(reduce_values([p[1] for p in f["points"]], calc), index, f) for index, f in enumerate(frames)]
    present = [s for s in scored if s[0] is not None]
    present.sort(key=lambda s: (s[0], -s[1]), reverse=reverse)
    return [s[2] for s in present[: max(0, count)]]


OPS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def apply_functions(frames, functions, interval_ms, anchor_ms=0):
    """Apply post-query functions in order; returns new frame list."""
    current = [dict(f, points=list(f["points"])) for f in frames if f["type"] == "timeseries"]
    passthrough = [f for f in frames if f["type"] != "timeseries"]
    for raw in functions or []:
        fn = normalize(raw)
        name = fn["name"]
        if name in QUERY_LEVEL:
            continue
        if name == "groupBy":
            step = parse_duration(_param(fn, 0)) * 1000
            method = _param(fn, 1)
            current = [dict(f, points=bucketize(f["points"], step, method, anchor_ms)) for f in current]
        elif name in ("scale", "offset"):
            factor = _number(_param(fn, 0))
            op = (lambda v, k=factor: v * k) if name == "scale" else (lambda v, k=factor: v + k)
            current = [dict(f, points=[[t, None if v is None else op(v)] for t, v in f["points"]]) for f in current]
        elif name in ("delta", "rate"):
            updated = []
            for f in current:
                out, previous = [], None
                for ts, value in f["points"]:
                    if value is None or previous is None or previous[1] is None:
                        out.append([ts, None])
                    else:
                        diff = value - previous[1]
                        if name == "rate":
                            seconds = (ts - previous[0]) / 1000
                            diff = None if diff < 0 or seconds <= 0 else diff / seconds
                        out.append([ts, diff])
                    if value is not None:
                        previous = [ts, value]
                updated.append(dict(f, points=out))
            current = updated
        elif name == "movingAverage":
            window = max(1, min(int(_number(_param(fn, 0))), MAX_WINDOW))
            updated = []
            for f in current:
                values = [v for _, v in f["points"]]
                out = []
                for index, (ts, _) in enumerate(f["points"]):
                    chunk = [v for v in values[max(0, index - window + 1) : index + 1] if v is not None]
                    out.append([ts, sum(chunk) / len(chunk) if chunk else None])
                updated.append(dict(f, points=out))
            current = updated
        elif name == "exponentialMovingAverage":
            window = max(1, min(int(_number(_param(fn, 0))), MAX_WINDOW))
            alpha = 2 / (window + 1)
            updated = []
            for f in current:
                ema, out = None, []
                for ts, value in f["points"]:
                    if value is not None:
                        ema = value if ema is None else alpha * value + (1 - alpha) * ema
                    out.append([ts, ema if value is not None else None])
                updated.append(dict(f, points=out))
            current = updated
        elif name == "percentile":
            step = parse_duration(_param(fn, 0)) * 1000
            fraction = _number(_param(fn, 1)) / 100
            updated = []
            for f in current:
                groups = defaultdict(list)
                for ts, value in f["points"]:
                    if value is not None:
                        groups[bucket_key(ts, step, anchor_ms)].append(value)
                updated.append(dict(f, points=[[ts, _pct(v, fraction)] for ts, v in sorted(groups.items())]))
            current = updated
        elif name in ("removeAboveValue", "removeBelowValue"):
            limit = _number(_param(fn, 0))
            above = name == "removeAboveValue"
            current = [dict(f, points=[[t, None if v is not None and ((v > limit) if above else (v < limit)) else v] for t, v in f["points"]]) for f in current]
        elif name == "transformNull":
            fill = _number(_param(fn, 0))
            current = [dict(f, points=[[t, fill if v is None else v] for t, v in f["points"]]) for f in current]
        elif name == "absolute":
            current = [dict(f, points=[[t, None if v is None else abs(v)] for t, v in f["points"]]) for f in current]
        elif name in ("aggregateBy", "sumSeries", "averageSeries", "maxSeries", "minSeries", "percentileAgg"):
            if not current:
                continue
            if name == "aggregateBy":
                step, method = parse_duration(_param(fn, 0)) * 1000, _param(fn, 1)
            elif name == "percentileAgg":
                step, method = parse_duration(_param(fn, 0)) * 1000, "percentile"
            else:
                step = interval_ms
                method = {"sumSeries": "sum", "averageSeries": "avg", "maxSeries": "max", "minSeries": "min"}[name]
            if method == "percentile":
                fraction = _number(_param(fn, 1)) / 100
                buckets = defaultdict(list)
                for f in current:
                    for ts, value in bucketize(f["points"], step, "avg", anchor_ms):
                        if value is not None:
                            buckets[ts].append(value)
                frame = ts_frame(
                    f"p{_number(_param(fn, 1)):g}(seriler)",
                    [[ts, _pct(v, fraction)] for ts, v in sorted(buckets.items())],
                    labels=_common_labels(current),
                    unit=current[0].get("unit", ""),
                    ref_id=current[0].get("refId", ""),
                    meta={"aggregated_series": len(current)},
                )
            else:
                frame = _combine(current, step, method, f"{method}({len(current)} seri)", anchor_ms)
            current = [frame]
        elif name == "groupByLabel":
            label, method = str(_param(fn, 0)), _param(fn, 1)
            groups = defaultdict(list)
            for f in current:
                groups[(f.get("labels") or {}).get(label, "—")].append(f)
            merged = []
            for key, members in sorted(groups.items()):
                frame = _combine(members, interval_ms, method, f"{key}", anchor_ms)
                frame["labels"] = {**frame["labels"], label: key}
                merged.append(frame)
            current = merged
        elif name in ("top", "bottom"):
            current = _select(current, fn, reverse=name == "top")
        elif name == "sortSeries":
            reverse = str(_param(fn, 0)).lower() != "asc"
            scored = [(reduce_values([p[1] for p in f["points"]], "mean"), f) for f in current]
            present = sorted((s for s in scored if s[0] is not None), key=lambda s: s[0], reverse=reverse)
            current = [f for _, f in present] + [f for score, f in scored if score is None]
        elif name == "filterSeries":
            calc, op, threshold = _param(fn, 0), str(_param(fn, 1)), _number(_param(fn, 2))
            if op not in OPS:
                raise FunctionError("Invalid comparison operator")
            current = [
                f
                for f in current
                if (value := reduce_values([p[1] for p in f["points"]], "mean" if calc == "avg" else calc)) is not None and OPS[op](value, threshold)
            ]
        elif name == "setAlias":
            template = str(_param(fn, 0))
            current = [dict(f, name=alias(template, f)) for f in current]
        elif name == "replaceAlias":
            pattern, replacement = _regex(_param(fn, 0)), str(_param(fn, 1))
            replacement = re.sub(r"\$(\d+)", r"\\\1", replacement)
            current = [dict(f, name=pattern.sub(replacement, f["name"])) for f in current]
        elif name == "setAliasByRegex":
            pattern = _regex(_param(fn, 0))
            updated = []
            for f in current:
                match = pattern.search(f["name"])
                updated.append(dict(f, name=(match.group(1) if match and match.groups() else match.group(0)) if match else f["name"]))
            current = updated
    return current + passthrough


def _pct(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * min(1.0, max(0.0, fraction))
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def query_option(functions, name, default=None):
    """Return the first parameter of a query-level function such as timeShift."""
    for raw in functions or []:
        fn = normalize(raw)
        if fn["name"] == name:
            return _param(fn, 0)
    return default
