"""Uniform data frames passed between datasources, functions and renderers.

A *time-series* frame carries ``points`` as ``[[epoch_ms, value_or_None], ...]``
sorted by time. A *table* frame carries typed ``columns`` and ``rows``. Missing
samples remain ``None``; nothing in the pipeline turns them into zero.
"""
import math
import statistics

REDUCERS = {
    "lastNotNull": "Son değer (boş olmayan)", "last": "Son değer", "firstNotNull": "İlk değer (boş olmayan)",
    "first": "İlk değer", "mean": "Ortalama", "min": "En düşük", "max": "En yüksek", "sum": "Toplam",
    "count": "Örnek sayısı", "range": "Aralık (max-min)", "delta": "Delta (sayaç)", "diff": "Fark (son-ilk)",
    "median": "Medyan", "p90": "90. yüzdelik", "p95": "95. yüzdelik", "p99": "99. yüzdelik",
    "stdDev": "Standart sapma", "changeCount": "Değişim sayısı", "distinctCount": "Farklı değer sayısı",
    "allIsNull": "Tümü boş", "allIsZero": "Tümü sıfır", "nullCount": "Boş örnek sayısı",
}


def ts_frame(name, points, *, labels=None, unit="", ref_id="", meta=None):
    return {"type": "timeseries", "name": str(name), "labels": dict(labels or {}), "unit": unit or "",
            "refId": ref_id, "points": points, "meta": dict(meta or {})}


def table_frame(name, columns, rows, *, ref_id="", meta=None):
    normalized = []
    for column in columns:
        if isinstance(column, str):
            column = {"name": column, "type": "string"}
        normalized.append({"name": str(column["name"]), "type": column.get("type", "string"),
                           **({"unit": column["unit"]} if column.get("unit") else {})})
    return {"type": "table", "name": str(name), "refId": ref_id, "columns": normalized,
            "rows": [list(row) for row in rows], "meta": dict(meta or {})}


def finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[int(position)]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def reduce_values(values, calc):
    """Reduce a list of raw values (None allowed) with a Grafana reducer id."""
    clean = [v for v in values if v is not None]
    if calc == "allIsNull":
        return 1.0 if not clean else 0.0
    if calc == "nullCount":
        return float(len(values) - len(clean))
    if calc == "count":
        return float(len(clean))
    if calc == "last":
        return values[-1] if values else None
    if calc == "first":
        return values[0] if values else None
    if not clean:
        return None
    if calc == "lastNotNull":
        return clean[-1]
    if calc == "firstNotNull":
        return clean[0]
    if calc == "mean":
        return sum(clean) / len(clean)
    if calc == "min":
        return min(clean)
    if calc == "max":
        return max(clean)
    if calc == "sum":
        return sum(clean)
    if calc == "range":
        return max(clean) - min(clean)
    if calc == "diff":
        return clean[-1] - clean[0]
    if calc == "delta":
        total = 0.0
        for previous, current in zip(clean, clean[1:]):
            total += current - previous if current >= previous else current
        return total
    if calc == "median":
        return float(statistics.median(clean))
    if calc in ("p90", "p95", "p99"):
        return _percentile(clean, int(calc[1:]) / 100)
    if calc == "stdDev":
        return float(statistics.pstdev(clean)) if len(clean) > 1 else 0.0
    if calc == "changeCount":
        return float(sum(1 for a, b in zip(clean, clean[1:]) if a != b))
    if calc == "distinctCount":
        return float(len(set(clean)))
    if calc == "allIsZero":
        return 1.0 if all(v == 0 for v in clean) else 0.0
    raise ValueError(f"Unknown reducer: {calc}")


def reduce_points(points, calc):
    return reduce_values([p[1] for p in points], calc)


def display_name(frame):
    meta = frame.get("meta") or {}
    return meta.get("displayName") or frame.get("name") or frame.get("refId") or "seri"


def total_points(frames):
    return sum(len(f.get("points", ())) if f["type"] == "timeseries" else len(f.get("rows", ()))
               for f in frames)
