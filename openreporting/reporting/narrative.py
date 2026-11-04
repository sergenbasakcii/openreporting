"""Smart narrative: plain-language findings computed from a panel's series (same rules as narrative.js).

Only facts derived from the data are stated: averages, extremes with their host and time, a trend
between the first and second half of the period, threshold breaches and the previous-period change.
"""

from datetime import datetime, timezone

from ..frames import finite
from ..timerange import zone
from ..units import format_value, resolve_unit
from .fieldcfg import display_name, options

MAX_NAMES = 5
TREND_MIN = 0.05  # changes below 5 % are reported as stable


def _values(frame):
    return [(t, v) for t, v in frame["points"] if finite(v) is not None]


def _series(frames):
    current = [f for f in frames if f["type"] == "timeseries" and not (f.get("meta") or {}).get("previous")]
    previous = [f for f in frames if f["type"] == "timeseries" and (f.get("meta") or {}).get("previous")]
    return current, previous


def _mean(values):
    return sum(values) / len(values) if values else None


def _names(items):
    names = [n for n, _ in items[:MAX_NAMES]]
    more = len(items) - len(names)
    return ", ".join(names) + (f" ve {more} diğer" if more > 0 else "")


def sentences(panel, frames, tz="UTC"):
    """List of finding sentences for the panel's data (empty when there is nothing to say)."""
    current, previous = _series(frames)
    series = [(display_name(f), _values(f), f) for f in current]
    series = [s for s in series if s[1]]
    if not series:
        return []
    unit = resolve_unit(((panel.get("fieldConfig") or {}).get("defaults") or {}).get("unit"), series[0][2].get("unit"))
    decimals = ((panel.get("fieldConfig") or {}).get("defaults") or {}).get("decimals")
    fmt = lambda v: format_value(v, unit, decimals)  # noqa: E731 - local formatter
    subject = options(panel, "subject", "") or panel.get("title") or "Değer"
    all_points = [(t, v, name) for name, values, _ in series for t, v in values]
    overall = _mean([v for _, v, _ in all_points])
    peak = max(all_points, key=lambda p: p[1])
    low = min(all_points, key=lambda p: p[1])
    when = datetime.fromtimestamp(peak[0] / 1000, timezone.utc).astimezone(zone(tz)).strftime("%d.%m %H:%M")
    out = [f"{subject} dönem boyunca ortalama {fmt(overall)}; en yüksek {fmt(peak[1])} ({peak[2]}, {when}), en düşük {fmt(low[1])}."]
    if len(series) > 1:
        ranked = sorted(((name, _mean([v for _, v in values])) for name, values, _ in series), key=lambda x: x[1], reverse=True)
        out.append(f"En yüksek ortalama {ranked[0][0]} ({fmt(ranked[0][1])}), en düşük {ranked[-1][0]} ({fmt(ranked[-1][1])}); {len(series)} seri incelendi.")
    ordered = sorted((t, v) for _, v_list, _ in series for t, v in v_list)
    half = len(ordered) // 2
    if half >= 2:
        first, second = _mean([v for _, v in ordered[:half]]), _mean([v for _, v in ordered[half:]])
        if first:
            change = (second - first) / abs(first)
            if abs(change) < TREND_MIN:
                out.append("Dönem içinde belirgin bir eğilim yok; değerler kararlı.")
            else:
                out.append(f"Dönemin ikinci yarısında ilk yarıya göre %{abs(change) * 100:.0f} {'arttı' if change > 0 else 'azaldı'}.")
    steps = [s for s in ((((panel.get("fieldConfig") or {}).get("defaults") or {}).get("thresholds") or {}).get("steps") or []) if s.get("value") is not None]
    if steps:
        top = max(steps, key=lambda s: float(s["value"]))
        breaches = sorted(((name, values[-1][1]) for name, values, _ in series if values[-1][1] >= float(top["value"])), key=lambda x: x[1], reverse=True)
        if breaches:
            out.append(f"{len(breaches)} seri son değerde {fmt(float(top['value']))} eşiğinin üzerinde: {_names(breaches)}.")
        else:
            out.append(f"Hiçbir seri {fmt(float(top['value']))} eşiğini aşmıyor.")
    prev_values = [v for f in previous for _, v in _values(f)]
    if prev_values and _mean(prev_values):
        change = (overall - _mean(prev_values)) / abs(_mean(prev_values))
        out.append(
            f"Önceki döneme göre ortalama %{abs(change) * 100:.1f} {'arttı' if change > 0 else 'azaldı' if change < 0 else 'değişmedi'}.".replace(".", ",", 1)
        )
    return out
