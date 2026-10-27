"""Server-side variable resolution and panel/row repetition.

The browser has the same logic in ``static/app/variables.js``/``layout.js``.
Reports use this module so that "repeat for each host in $group" produces the
same panels in the PDF as on screen.
"""
import copy
import re

from . import datasources, query_engine
from .datasources.base import DataSourceError
from .domain import DomainError
from .safe_regex import compile_slashed
from .templating import ALL, interpolate

SORTS = {1: (False, False), 2: (False, True), 3: (True, False), 4: (True, True), 5: (False, False, True),
         6: (False, True, True), 7: (True, False, True), 8: (True, True, True)}


def _options_from_custom(query):
    options = []
    for part in re.split(r"(?<!\\),", str(query or "")):
        part = part.replace("\\,", ",").strip()
        if not part:
            continue
        if " : " in part:
            text, value = part.split(" : ", 1)
            options.append({"text": text.strip(), "value": value.strip()})
        else:
            options.append({"text": part, "value": part})
    return options


def _apply_regex(options, regex):
    if not regex:
        return options
    pattern = compile_slashed(regex)
    result, seen = [], set()
    for option in options:
        found = pattern.search(str(option["text"]))
        if not found:
            continue
        groups = found.groupdict() if hasattr(found, "groupdict") else {}
        if groups.get("text") or groups.get("value"):
            option = {"text": groups.get("text") or groups.get("value"), "value": groups.get("value") or groups.get("text")}
        elif found.groups():
            option = {"text": found.group(1), "value": found.group(1)}
        if option["value"] not in seen:
            seen.add(option["value"])
            result.append(option)
    return result


def _sort(options, sort):
    sort = int(sort or 0)
    if sort not in SORTS:
        return options
    numeric = sort in (3, 4)
    case_insensitive = sort in (5, 6)
    reverse = sort in (2, 4, 6)

    def key(option):
        text = str(option["text"])
        if numeric:
            found = re.search(r"-?\d+(\.\d+)?", text)
            return float(found.group(0)) if found else float("inf")
        return text.casefold() if case_insensitive else text

    return sorted(options, key=key, reverse=reverse)


def variable_options(settings, var, resolved, request, *, user="", trusted=True):
    kind = var.get("type")
    if kind == "custom":
        return _options_from_custom(interpolate(var.get("query", ""), resolved))
    if kind == "interval":
        return _options_from_custom(var.get("query") or "1m,10m,30m,1h,6h,12h,1d,7d")
    if kind == "datasource":
        wanted = var.get("query") or ""
        return [{"text": d["name"], "value": d["uid"]} for d in datasources.list_all(settings)
                if not wanted or d["type"] == wanted]
    if kind in ("constant", "textbox"):
        value = str(var.get("query") or "")
        return [{"text": value, "value": value}]
    ds_ref = var.get("datasource")
    uid = ds_ref.get("uid") if isinstance(ds_ref, dict) else ds_ref
    query = var.get("query")
    if isinstance(query, dict) and "query" in query and len(query) <= 3 and not query.get("type"):
        query = query.get("query")
    found = query_engine.metric_find(settings, uid, query, {**request, "variables": resolved}, user=user,
                                     trusted=trusted)
    options = [{"text": str(o.get("text")), "value": str(o.get("value", o.get("text")))} for o in found]
    return _sort(_apply_regex(options, var.get("regex")), var.get("sort"))


def _pick(var, options, override):
    multi = var.get("multi")
    include_all = var.get("includeAll")
    values = [o["value"] for o in options]
    wanted = override
    if wanted is None:
        current = (var.get("current") or {}).get("value")
        wanted = current
    if isinstance(wanted, str) and wanted.lower() in ("all", ALL) and include_all:
        wanted = [ALL]
    if wanted in (None, "", []):
        if include_all and (var.get("type") == "query" and (var.get("current") or {}).get("value") in (None, ALL, [ALL])):
            return [ALL] if multi else ALL
        return ([values[0]] if multi else values[0]) if values else ([] if multi else "")
    if isinstance(wanted, list):
        chosen = [w for w in wanted if w == ALL or w in values or var.get("type") in ("textbox", "constant")]
        if not chosen:
            chosen = [values[0]] if values else []
        return chosen if multi else chosen[0] if chosen else ""
    if var.get("type") in ("textbox", "constant") or wanted in values or wanted == ALL:
        return [wanted] if multi else wanted
    return ([values[0]] if multi else values[0]) if values else ([] if multi else "")


def resolve_variables(settings, dashboard, overrides=None, request=None, *, user="", trusted=True):
    """Return {name: {value, text, options, multi, includeAll, allValue}} in dependency order."""
    overrides = overrides or {}
    request = request or {"range": dashboard.get("time") or {"from": "now-6h", "to": "now"},
                          "timezone": "UTC"}
    resolved = {}
    warnings = []
    for var in (dashboard.get("templating") or {}).get("list", []):
        name = var["name"]
        try:
            options = variable_options(settings, var, resolved, request, user=user, trusted=trusted)
        except (DataSourceError, DomainError, ValueError) as exc:
            warnings.append(f"${name}: seçenekler alınamadı ({exc})")
            options = []
        value = _pick(var, options, overrides.get(name))
        values = value if isinstance(value, list) else [value]
        text = " + ".join("Tümü" if v == ALL else next((o["text"] for o in options if o["value"] == v), v)
                          for v in values)
        resolved[name] = {"value": value, "text": text, "options": options, "multi": bool(var.get("multi")),
                          "includeAll": bool(var.get("includeAll")), "allValue": var.get("allValue") or None,
                          "type": var.get("type"), "label": var.get("label") or name}
    return resolved, warnings


def expanded_values(variable):
    value = variable.get("value")
    values = value if isinstance(value, list) else [value]
    if ALL in values:
        return [o["value"] for o in variable.get("options", []) if o["value"] != ALL]
    return [v for v in values if v not in (None, "")]


def _scoped(variables, name, value):
    var = variables.get(name, {})
    text = next((o["text"] for o in var.get("options", []) if o["value"] == value), value)
    return {**variables, name: {**var, "value": value, "text": text, "multi": False, "includeAll": False}}


def flatten(panels, include_collapsed=True):
    """Rows' collapsed children become top-level panels below their row."""
    result = []
    for panel in sorted(panels, key=lambda p: (p["gridPos"]["y"], p["gridPos"]["x"])):
        result.append(panel)
        if panel.get("type") == "row" and panel.get("collapsed") and include_collapsed:
            base = panel["gridPos"]["y"] + 1
            for child in sorted(panel.get("panels", []), key=lambda p: (p["gridPos"]["y"], p["gridPos"]["x"])):
                child = copy.deepcopy(child)
                child["gridPos"] = {**child["gridPos"], "y": base + child["gridPos"]["y"]}
                result.append(child)
    return result


def compact(panels):
    """Vertical gravity compaction (react-grid-layout semantics)."""
    placed = []
    for panel in sorted(panels, key=lambda p: (p["gridPos"]["y"], p["gridPos"]["x"])):
        pos = dict(panel["gridPos"])
        y = 0
        while True:
            collision = next((q for q in placed if pos["x"] < q["x"] + q["w"] and q["x"] < pos["x"] + pos["w"]
                              and y < q["y"] + q["h"] and q["y"] < y + pos["h"]), None)
            if collision is None:
                break
            y = collision["y"] + collision["h"]
        pos["y"] = y
        placed.append(pos)
        panel["gridPos"] = pos
    return sorted(panels, key=lambda p: (p["gridPos"]["y"], p["gridPos"]["x"]))


def expand(dashboard, variables, include_collapsed=True):
    """Return render-ready panels: rows/panels repeated, each with ``scopedVars``."""
    panels = flatten(copy.deepcopy(dashboard.get("panels", [])), include_collapsed)
    sections = []  # (row or None, [panels])
    current = [None, []]
    for panel in panels:
        if panel.get("type") == "row":
            sections.append(current)
            current = [panel, []]
        else:
            current[1].append(panel)
    sections.append(current)
    output = []
    y_offset = 0
    for row, members in sections:
        if row is None and not members:
            continue
        repeat = row.get("repeat") if row else None
        values = expanded_values(variables[repeat]) if repeat and repeat in variables else [None]
        for value in values:
            scope = _scoped(variables, repeat, value) if value is not None else variables
            if row is not None:
                row_copy = copy.deepcopy(row)
                row_copy["scopedVars"] = {repeat: scope[repeat]} if value is not None else {}
                row_copy["title"] = interpolate(row_copy.get("title", ""), scope)
                row_copy["gridPos"] = {**row_copy["gridPos"], "y": y_offset}
                output.append(row_copy)
                y_offset += 1
            base_y = min((p["gridPos"]["y"] for p in members), default=0)
            section_height = 0
            for panel in members:
                repeat_var = panel.get("repeat")
                panel_values = (expanded_values(scope[repeat_var]) if repeat_var and repeat_var in scope else [None])
                rel_y = panel["gridPos"]["y"] - base_y
                count = len(panel_values)
                per_row = int(panel.get("maxPerRow") or 0) or max(1, 24 // max(1, panel["gridPos"]["w"]))
                width = panel["gridPos"]["w"] if panel.get("repeatDirection") == "v" or count == 1 else \
                    max(1, 24 // max(1, min(count, per_row)))
                for index, pv in enumerate(panel_values):
                    clone = copy.deepcopy(panel)
                    local = _scoped(scope, repeat_var, pv) if pv is not None else scope
                    scoped = {}
                    if value is not None:
                        scoped[repeat] = local[repeat]
                    if pv is not None:
                        scoped[repeat_var] = local[repeat_var]
                    clone["scopedVars"] = scoped
                    clone["title"] = interpolate(clone.get("title", ""), local)
                    if pv is not None and index:
                        clone["id"] = clone["id"] * 1000 + index
                    h = clone["gridPos"]["h"]
                    if panel.get("repeatDirection") == "v":
                        clone["gridPos"] = {**clone["gridPos"], "y": y_offset + rel_y + index * h}
                    else:
                        line, col = divmod(index, max(1, min(count, per_row)))
                        x = panel["gridPos"]["x"] if count == 1 else col * width
                        clone["gridPos"] = {"x": x, "y": y_offset + rel_y + line * h, "w": width, "h": h}
                    section_height = max(section_height, clone["gridPos"]["y"] - y_offset + h)
                    output.append(clone)
            y_offset += section_height
    return compact(output)
