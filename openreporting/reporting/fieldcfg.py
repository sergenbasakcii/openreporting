"""Python mirror of the browser's field-config, thresholds and colors (static/app/colors.js)."""

import copy
import math
import re

from ..frames import reduce_values
from ..safe_regex import RegexError, compile_slashed
from ..units import format_value, resolve_unit

NAMED = {
    "green": "#73BF69",
    "dark-green": "#37872D",
    "semi-dark-green": "#56A64B",
    "light-green": "#96D98D",
    "yellow": "#FADE2A",
    "dark-yellow": "#E0B400",
    "semi-dark-yellow": "#F2CC0C",
    "light-yellow": "#FFEE52",
    "red": "#F2495C",
    "dark-red": "#C4162A",
    "semi-dark-red": "#E02F44",
    "light-red": "#FF7383",
    "blue": "#5794F2",
    "dark-blue": "#1F60C4",
    "semi-dark-blue": "#3274D9",
    "light-blue": "#8AB8FF",
    "orange": "#FF9830",
    "dark-orange": "#FA6400",
    "semi-dark-orange": "#FF780A",
    "light-orange": "#FFB357",
    "purple": "#B877D9",
    "dark-purple": "#8F3BB8",
    "semi-dark-purple": "#A352CC",
    "light-purple": "#CA95E5",
    "text": "#404450",
    "white": "#FFFFFF",
    "black": "#000000",
    "transparent": "#FFFFFF",
}
# Reports are printed on white: the Porcelain theme's series colours first (see static/app/themes.css),
# then the classic colours for long legends.
SERIES = ["#0d9488", "#4f46e5", "#d97706", "#db2777", "#2563eb", "#65a30d", "#ea580c", "#9333ea", "#0891b2", "#dc2626"]
CLASSIC = [
    "#73BF69",
    "#F2CC0C",
    "#8AB8FF",
    "#FF780A",
    "#F2495C",
    "#5794F2",
    "#B877D9",
    "#705DA0",
    "#37872D",
    "#FADE2A",
    "#447EBC",
    "#C15C17",
    "#890F02",
    "#0A437C",
    "#6D1F62",
    "#584477",
    "#B7DBAB",
    "#F4D598",
    "#70DBED",
    "#F9BA8F",
]
PALETTE = SERIES + [c for c in CLASSIC if c not in SERIES]
DEFAULT_THRESHOLDS = {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "red", "value": 80}]}

PANEL_DEFAULTS = {
    "timeseries": {
        "options": {"legend": {"showLegend": True, "displayMode": "list", "calcs": []}},
        "custom": {"drawStyle": "line", "fillOpacity": 10, "lineWidth": 1},
        "color": "palette-classic",
    },
    "barchart": {"options": {"reduceOptions": {"calcs": ["mean"]}}, "color": "palette-classic"},
    "stat": {"options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value", "graphMode": "area", "textMode": "auto"}, "color": "thresholds"},
    "gauge": {"options": {"reduceOptions": {"calcs": ["lastNotNull"]}}, "color": "thresholds", "min": 0, "max": 100},
    "bargauge": {"options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "displayMode": "gradient"}, "color": "thresholds"},
    "table": {"options": {}, "color": "thresholds"},
    "piechart": {"options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "pieType": "pie"}, "color": "palette-classic"},
    "statusgrid": {"options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "labelField": "host", "sort": "name"}, "color": "thresholds"},
    "statetimeline": {"options": {}, "color": "thresholds"},
}


def color(name):
    if not name:
        return PALETTE[0]
    name = str(name)
    if name in NAMED:
        return NAMED[name]
    if re.fullmatch(r"#[0-9a-fA-F]{6}", name):
        return name
    match = re.fullmatch(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", name)
    if match:
        return "#%02x%02x%02x" % tuple(int(x) for x in match.groups())
    return PALETTE[0]


def options(panel, path, default=None):
    node = panel.get("options") or {}
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            fallback = PANEL_DEFAULTS.get(panel.get("type"), {}).get("options", {})
            for part in path.split("."):
                fallback = fallback.get(part) if isinstance(fallback, dict) else None
            return default if fallback is None else fallback
        node = node[key]
    return node


def _set(cfg, path, value):
    parts = path.split(".")
    node = cfg
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


def _matches(matcher, frame, name):
    if not isinstance(matcher, dict):
        return False
    option = matcher.get("options")
    kind = matcher.get("id")
    if kind == "byName":
        return name == option
    if kind == "byRegexp":
        try:
            return bool(compile_slashed(option).search(name))
        except RegexError:
            return False
    if kind == "byFrameRefID":
        return frame.get("refId") == option
    return False


def field_config(panel, frame, name):
    cfg = copy.deepcopy(((panel.get("fieldConfig") or {}).get("defaults")) or {})
    cfg.setdefault("custom", {})
    defaults = PANEL_DEFAULTS.get(panel.get("type"), {})
    for key, value in (defaults.get("custom") or {}).items():
        cfg["custom"].setdefault(key, value)
    if "color" not in cfg and defaults.get("color"):
        cfg["color"] = {"mode": defaults["color"]}
    for key in ("min", "max"):
        if key not in cfg and key in defaults:
            cfg[key] = defaults[key]
    for override in ((panel.get("fieldConfig") or {}).get("overrides")) or []:
        if _matches(override.get("matcher"), frame, name):
            for prop in override.get("properties") or []:
                if isinstance(prop, dict) and prop.get("id"):
                    _set(cfg, prop["id"], prop.get("value"))
    return cfg


def threshold_color(value, thresholds, low=0, high=100):
    steps = (thresholds or DEFAULT_THRESHOLDS).get("steps") or DEFAULT_THRESHOLDS["steps"]
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    v = float(value)
    if (thresholds or {}).get("mode") == "percentage":
        v = (v - low) / (high - low) * 100 if high > low else 0
    active = steps[0]
    for step in steps:
        if step.get("value") is None:
            active = step
            continue
        try:
            if v >= float(step["value"]):
                active = step
        except (TypeError, ValueError):
            continue
    return color(active.get("color"))


def series_color(cfg, index, value):
    mode = (cfg.get("color") or {}).get("mode", "palette-classic")
    if mode == "fixed":
        return color((cfg.get("color") or {}).get("fixedColor"))
    if mode == "thresholds":
        return threshold_color(value, cfg.get("thresholds"), cfg.get("min") or 0, cfg.get("max") or 100) or PALETTE[index % len(PALETTE)]
    return PALETTE[index % len(PALETTE)]


def display_name(frame):
    meta = frame.get("meta") or {}
    return meta.get("displayName") or frame.get("name") or frame.get("refId") or "seri"


def _mapping_keys(value):
    """Keys a browser would produce with String(value): 1.0 -> "1", True -> "true"."""
    keys = [str(value)]
    if isinstance(value, bool):
        keys.append(str(value).lower())
    elif isinstance(value, float) and value.is_integer():
        keys.insert(0, str(int(value)))
    return keys


def mapped(value, mappings):
    for mapping in mappings or []:
        opts = mapping.get("options") or {}
        if mapping.get("type") == "value":
            for key in _mapping_keys(value):
                if key in opts:
                    return opts[key]
        if mapping.get("type") == "range" and value is not None:
            low, high = opts.get("from"), opts.get("to")
            if (low is None or value >= low) and (high is None or value <= high):
                return opts.get("result") or {}
        if mapping.get("type") == "special" and value is None and opts.get("match") == "null":
            return opts.get("result") or {}
    return None


def fmt(value, cfg, unit):
    hit = mapped(value, cfg.get("mappings"))
    if hit and hit.get("text"):
        return hit["text"]
    if value is None:
        return cfg.get("noValue") or "Veri yok"
    return format_value(value, unit, cfg.get("decimals"))


def reduced_items(panel, frames):
    """One (name, value, unit, cfg, color, points, labels) per series/table cell — like common.js."""
    calc = (options(panel, "reduceOptions.calcs", ["lastNotNull"]) or ["lastNotNull"])[0]
    per_row = bool(options(panel, "reduceOptions.values", False))
    items = []
    index = 0
    for frame in frames:
        if (frame.get("meta") or {}).get("previous"):
            continue  # previous-period frames only feed comparisons
        if frame["type"] == "timeseries":
            name = display_name(frame)
            cfg = field_config(panel, frame, name)
            values = [p[1] for p in frame["points"]]
            value = reduce_values(values, calc)
            unit = resolve_unit(cfg.get("unit"), frame.get("unit"))
            label = cfg.get("displayName") or name
            items.append(
                {
                    "name": label,
                    "value": value,
                    "unit": unit,
                    "cfg": cfg,
                    "color": series_color(cfg, index, value),
                    "points": frame["points"],
                    "labels": frame.get("labels") or {},
                }
            )
            index += 1
        else:
            label_index = next((i for i, c in enumerate(frame["columns"]) if c["type"] == "string"), None)
            numeric = [i for i, c in enumerate(frame["columns"]) if c["type"] == "number"]
            for ci in numeric:
                column = frame["columns"][ci]
                cfg = field_config(panel, frame, column["name"])
                if per_row or label_index is not None:
                    for ri, row in enumerate(frame["rows"]):
                        row_units = (frame.get("meta") or {}).get("rowUnits") or []
                        unit = resolve_unit(cfg.get("unit"), column.get("unit") or (row_units[ri] if ri < len(row_units) else ""))
                        label = (
                            f"{row[label_index]}" + (f" · {column['name']}" if len(numeric) > 1 else "")
                            if label_index is not None
                            else f"{column['name']} {ri + 1}"
                        )
                        value = row[ci]
                        items.append(
                            {"name": label, "value": value, "unit": unit, "cfg": cfg, "color": series_color(cfg, index, value), "points": [], "labels": {}}
                        )
                        index += 1
                else:
                    value = reduce_values([r[ci] for r in frame["rows"]], calc)
                    unit = resolve_unit(cfg.get("unit"), column.get("unit"))
                    items.append(
                        {"name": column["name"], "value": value, "unit": unit, "cfg": cfg, "color": series_color(cfg, index, value), "points": [], "labels": {}}
                    )
                    index += 1
    limit = int(options(panel, "reduceOptions.limit", 0) or 0)
    items = items[:limit] if limit > 0 else items
    return top_n(panel, items)


def top_n(panel, items):
    """Keep the N highest (or lowest) items by value, sorted that way; ``options.topN`` = 0 keeps all."""
    try:
        n = int(options(panel, "topN", 0) or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return items
    lowest = options(panel, "topOrder", "desc") == "asc"
    ranked = sorted(items, key=lambda i: (i["value"] is None, (i["value"] or 0) if lowest else -(i["value"] or 0)))
    return ranked[: min(n, 500)]


def hex_rgb(value):
    value = color(value).lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))


def contrast(value):
    r, g, b = hex_rgb(value)
    return "#111111" if (r * 299 + g * 587 + b * 114) / 1000 > 0.59 else "#FFFFFF"
