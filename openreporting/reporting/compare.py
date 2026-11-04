"""Previous-period comparison for reports: per-item percentage change of the reduced value."""

from .fieldcfg import display_name, options
from ..frames import reduce_values

SUFFIX = " (önceki dönem)"


def comparison_deltas(panel, frames, items):
    """{item index: fractional change vs the previous period} for items whose series has a previous twin."""
    if options(panel, "compare", None) != "previous":
        return {}
    calc = (options(panel, "reduceOptions.calcs", ["lastNotNull"]) or ["lastNotNull"])[0]
    previous, ordered = {}, []
    for frame in frames:
        if (frame.get("meta") or {}).get("previous") and frame["type"] == "timeseries":
            value = reduce_values([p[1] for p in frame["points"]], calc)
            previous[display_name(frame).removesuffix(SUFFIX)] = value
            ordered.append(value)
    deltas = {}
    for index, item in enumerate(items):
        # Match by series name; same-order fallback when a display name override renamed both.
        before = previous.get(item["name"], ordered[index] if len(ordered) == len(items) else None)
        if before in (None, 0) or item["value"] is None:
            continue
        deltas[index] = (item["value"] - before) / abs(before)
    return deltas


def delta_text(delta, good="neutral"):
    """("▲ 12,5% önceki döneme göre", "good" | "bad" | "neutral")."""
    arrow = "▲" if delta > 0 else "▼" if delta < 0 else "■"
    tone = "neutral"
    if good in ("up", "down") and delta:
        tone = "good" if (delta > 0) == (good == "up") else "bad"
    return f"{arrow} %{abs(delta) * 100:.1f} önceki döneme göre".replace(".", ","), tone
