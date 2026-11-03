"""Dashboard variable interpolation (``$host``, ``${host:csv}``, ``[[host]]``).

Values are formatted for their destination: Zabbix filters receive anchored
regexes for multi-value selections, SQL receives escaped quoted literals. A
viewer-controlled textbox can therefore never inject raw SQL by default.
"""

import json
import re
from urllib.parse import quote

ALL = "$__all"
_PATTERN = re.compile(r"\$(\w+)|\[\[(\w+?)(?::(\w+))?\]\]|\$\{(\w+)(?::([^}]+))?\}")


def _values(variable):
    value = variable.get("value") if isinstance(variable, dict) else variable
    if isinstance(variable, dict) and variable.get("includeAll") and (value == ALL or (isinstance(value, list) and ALL in value)):
        if variable.get("allValue"):
            return None  # Grafana semantics: custom all value is used verbatim.
        options = variable.get("options") or []
        return [str(o.get("value") if isinstance(o, dict) else o) for o in options if (o.get("value") if isinstance(o, dict) else o) != ALL]
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _sql_quote(value):
    # PostgreSQL standard_conforming_strings=on: only the quote needs doubling.
    text = str(value).replace("\x00", "")
    return "'" + text.replace("'", "''") + "'"


def format_values(values, fmt, *, multi=False, name=""):
    if fmt == "promql":
        # A regex value inside a double-quoted PromQL/LogQL label matcher.
        escaped = [re.sub(r"([\\.^$|?*+(){}\[\]])", r"\\\1", v) for v in values]
        pattern = escaped[0] if len(escaped) == 1 else "(" + "|".join(escaped) + ")"
        return json.dumps(pattern, ensure_ascii=False)[1:-1]
    if fmt in (None, "", "raw"):
        if len(values) == 1 and not multi:
            return values[0]
        return values[0] if len(values) == 1 else "{" + ",".join(values) + "}"
    if fmt == "regex":
        escaped = [re.escape(v) for v in values]
        return escaped[0] if len(escaped) == 1 else "(" + "|".join(escaped) + ")"
    if fmt == "zabbix":
        if len(values) == 1 and not values[0].startswith("/"):
            return values[0]
        return "/^(?:" + "|".join(re.escape(v) for v in values) + ")$/"
    if fmt == "pipe":
        return "|".join(values)
    if fmt == "csv":
        return ",".join(values)
    if fmt == "json":
        return json.dumps(values if multi or len(values) != 1 else values[0], ensure_ascii=False)
    if fmt == "sqlstring":
        return ",".join(_sql_quote(v) for v in values) if values else "NULL"
    if fmt == "doublequote":
        return ",".join('"' + v.replace('"', '\\"') + '"' for v in values)
    if fmt == "singlequote":
        return ",".join("'" + v.replace("'", "\\'") + "'" for v in values)
    if fmt == "glob":
        return values[0] if len(values) == 1 else "{" + ",".join(values) + "}"
    if fmt in ("text", "text_value"):
        return " + ".join(values)
    if fmt == "queryparam":
        return "&".join(f"var-{quote(name)}={quote(v)}" for v in values)
    if fmt == "percentencode":
        return quote(values[0] if len(values) == 1 else "{" + ",".join(values) + "}", safe="")
    if fmt in ("lucene",):
        return "(" + " OR ".join('"' + v.replace('"', '\\"') + '"' for v in values) + ")"
    return ",".join(values)


# Formats that keep a value inert inside the datasource's own syntax.
SAFE_FORMATS = {"sqlstring": {"sqlstring"}, "zabbix": {"zabbix", "regex", "csv", "pipe", "text", "json", "glob"}}


def validate_promql_variables(text, variables, builtins):
    # User variables are only allowed inside double-quoted label strings.
    # Escaping a value is not sufficient if the author places it as syntax.
    # Single-quoted and backtick (raw) strings are tracked too, so a '"' inside them
    # cannot flip the state and make a later bare $var look quoted.
    state, escaped, inside = None, False, set()
    for i, char in enumerate(text):
        if state is None:
            if char in "\"'`":
                state = char
            continue
        if state == '"':
            inside.add(i)
        if escaped:
            escaped = False
        elif char == "\\" and state != "`":
            escaped = True
        elif char == state:
            state = None
    if state is not None and _PATTERN.search(text):
        raise ValueError("PromQL/LogQL sorgusunda kapanmamış tırnak var")
    for match in _PATTERN.finditer(text):
        name = match.group(1) or match.group(2) or match.group(4)
        if name in variables and name not in builtins and match.start() not in inside:
            raise ValueError("PromQL/LogQL değişkenlerini çift tırnaklı etiket değerleri içinde kullanın")


def interpolate(text, variables, *, default_format=None, builtins=None, strict=False):
    """Replace variables in ``text``; unknown variables are left untouched.

    ``strict`` (viewer-initiated queries) forces a format that cannot break out of
    the target syntax: e.g. ``${var:raw}`` in SQL becomes a quoted literal.
    """
    if not isinstance(text, str) or "$" not in text and "[[" not in text:
        return text
    variables = variables or {}
    builtins = builtins or {}

    def replace(match):
        name = match.group(1) or match.group(2) or match.group(4)
        fmt = match.group(3) or match.group(5)
        if strict and default_format and fmt not in SAFE_FORMATS.get(default_format, {default_format}):
            fmt = default_format
        if name in builtins:
            value = builtins[name]
            return str(value)
        variable = variables.get(name)
        if variable is None:
            return match.group(0)
        values = _values(variable)
        if values is None:
            return str(variable.get("allValue"))
        multi = bool(isinstance(variable, dict) and (variable.get("multi") or variable.get("includeAll")))
        return format_values(values, fmt or default_format, multi=multi and len(values) != 1, name=name)

    return _PATTERN.sub(replace, text)


def interpolate_deep(value, variables, *, default_format=None, builtins=None, skip_keys=("refId", "datasource"), strict=False):
    """Recursively interpolate every string inside a query target."""
    if isinstance(value, str):
        return interpolate(value, variables, default_format=default_format, builtins=builtins, strict=strict)
    if isinstance(value, list):
        return [interpolate_deep(v, variables, default_format=default_format, builtins=builtins, strict=strict, skip_keys=skip_keys) for v in value]
    if isinstance(value, dict):
        return {
            k: (v if k in skip_keys else interpolate_deep(v, variables, default_format=default_format, strict=strict, builtins=builtins, skip_keys=skip_keys))
            for k, v in value.items()
        }
    return value


def builtin_variables(start, end, interval_s, *, dashboard="", user="", timezone_name="UTC"):
    interval_ms = int(interval_s * 1000)
    from .timerange import format_duration

    range_s = int((end - start).total_seconds())
    return {
        "__interval": format_duration(interval_s),
        "__interval_ms": interval_ms,
        "__from": int(start.timestamp() * 1000),
        "__to": int(end.timestamp() * 1000),
        "__range": format_duration(range_s) if range_s else "0s",
        "__range_s": range_s,
        "__range_ms": range_s * 1000,
        "__dashboard": dashboard,
        "__user": user,
        "__timezone": timezone_name,
        "__rate_interval": format_duration(max(interval_s * 4, 60)),
    }
