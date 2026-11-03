"""Server-side expressions over query results (Grafana "Expression" queries).

``$A * 8``, ``($A / $B) * 100``, ``abs($A - $B)``: parsed with :mod:`ast` and
evaluated through a strict whitelist — never ``eval``. Series are matched by
labels (host first), a single series is broadcast against many.
"""

import ast
import math
import re

from .domain import DomainError
from .frames import REDUCERS, reduce_values, ts_frame
from .series_functions import bucketize
from .timerange import parse_duration

_REF = re.compile(r"\$\{?([A-Z][A-Z0-9_]{0,15})\}?")
_FUNCS = {
    "abs": abs,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "sqrt": math.sqrt,
    "round": round,
    "floor": math.floor,
    "ceil": math.ceil,
    "min": min,
    "max": max,
    "is_null": None,
}
_BIN = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
    ast.FloorDiv: lambda a, b: a // b,
}
_CMP = {
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
}


class ExpressionError(DomainError):
    pass


def references(expression: str):
    return sorted(set(_REF.findall(expression or "")))


def compile_math(expression: str):
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 1000:
        raise ExpressionError("Math expression is empty or too long")
    source = _REF.sub(lambda m: f"__ref_{m.group(1)}", expression)
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        raise ExpressionError(f"Geçersiz ifade: {getattr(exc, 'msg', exc)}") from exc
    call_names = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for node in ast.walk(tree):
        if isinstance(node, ast.cmpop) and type(node) not in _CMP:
            raise ExpressionError("Desteklenmeyen karşılaştırma işleci")
        if isinstance(node, (ast.Expression, ast.Load, ast.operator, ast.unaryop, ast.cmpop, ast.boolop)):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            if not abs(node.value) < 1e300:  # also rejects inf/nan; huge ints would overflow float()
                raise ExpressionError("Sayı çok büyük")
            continue
        if isinstance(node, ast.Name) and node.id.startswith("__ref_"):
            continue
        if isinstance(node, ast.Name) and node.id in _FUNCS and id(node) in call_names:
            continue
        if isinstance(node, (ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp, ast.IfExp)):
            if isinstance(node, ast.BinOp) and type(node.op) not in _BIN:
                raise ExpressionError("Unsupported operator")
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords and len(node.args) <= 2:
            continue
        raise ExpressionError(f"Unsupported syntax in expression: {type(node).__name__}")
    return tree.body


def _eval(node, env):
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.UnaryOp):
        value = _eval(node.operand, env)
        if value is None:
            return None
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.Not):
            return float(not value)
        return value
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, env), _eval(node.right, env)
        if left is None or right is None:
            return None
        try:
            result = _BIN[type(node.op)](left, right)
        except (ZeroDivisionError, OverflowError, ValueError):
            return None
        return result if isinstance(result, (int, float)) and math.isfinite(result) else None
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, env)
            if left is None or right is None:
                return None
            if not _CMP[type(op)](left, right):
                return 0.0
            left = right
        return 1.0
    if isinstance(node, ast.BoolOp):
        values = [_eval(v, env) for v in node.values]
        if any(v is None for v in values):
            return None
        return float(all(values) if isinstance(node.op, ast.And) else any(values))
    if isinstance(node, ast.IfExp):
        test = _eval(node.test, env)
        if test is None:
            return None
        return _eval(node.body if test else node.orelse, env)
    if isinstance(node, ast.Call):
        name = node.func.id
        args = [_eval(a, env) for a in node.args]
        if name == "is_null":
            return 1.0 if args and args[0] is None else 0.0
        if any(a is None for a in args):
            return None
        try:
            result = _FUNCS[name](*args)
        except (ValueError, OverflowError, TypeError):
            return None
        return float(result) if math.isfinite(result) else None
    raise ExpressionError("Unsupported expression node")


def _match_key(frame):
    labels = frame.get("labels") or {}
    if "host" in labels:
        return ("host", labels["host"])
    return tuple(sorted(labels.items()))


def evaluate_math(expression, inputs, interval_ms, ref_id, anchor_ms=0):
    """inputs: refId -> list of time-series frames."""
    body = compile_math(expression)
    refs = references(expression)
    missing = [r for r in refs if r not in inputs]
    if missing:
        raise ExpressionError(f"Expression references unknown query: {', '.join(missing)}")
    aligned = {r: [dict(f, points=bucketize(f["points"], interval_ms, "avg", anchor_ms)) for f in inputs[r] if f["type"] == "timeseries"] for r in refs}
    if not refs:
        raise ExpressionError("Expression must reference at least one query, e.g. $A")
    driver = max(refs, key=lambda r: len(aligned[r]))
    warnings = []
    frames = []
    for base in aligned[driver]:
        partners = {}
        for ref in refs:
            if ref == driver:
                partners[ref] = base
                continue
            candidates = aligned[ref]
            if len(candidates) == 1:
                partners[ref] = candidates[0]
            else:
                match = [c for c in candidates if _match_key(c) == _match_key(base)]
                if len(match) != 1:
                    warnings.append(f"{base['name']}: ${ref} içinde eşleşen seri bulunamadı")
                    break
                partners[ref] = match[0]
        else:
            lookups = {ref: dict((t, v) for t, v in frame["points"]) for ref, frame in partners.items()}
            timestamps = sorted(set().union(*[set(lookup) for lookup in lookups.values()]))
            try:
                points = [[ts, _eval(body, {f"__ref_{ref}": lookups[ref].get(ts) for ref in refs})] for ts in timestamps]
            except RecursionError as exc:
                raise ExpressionError("İfade çok derin") from exc
            name = base["name"] if len(aligned[driver]) > 1 else expression
            frames.append(ts_frame(name, points, labels=base.get("labels"), unit=base.get("unit", ""), ref_id=ref_id, meta={"expression": expression}))
    return frames, warnings


def evaluate(expr_target, inputs, interval_ms, end_ms, anchor_ms=0):
    kind = expr_target.get("type", "math")
    ref_id = expr_target.get("refId", "")
    if kind == "math":
        return evaluate_math(expr_target.get("expression", ""), inputs, interval_ms, ref_id, anchor_ms)
    source = str(expr_target.get("expression", "")).lstrip("$").strip("{}")
    if source not in inputs:
        raise ExpressionError(f"Expression references unknown query: {source}")
    frames = [f for f in inputs[source] if f["type"] == "timeseries"]
    if kind == "reduce":
        reducer = expr_target.get("reducer", "mean")
        if reducer not in REDUCERS:
            raise ExpressionError(f"Bilinmeyen hesaplama: {reducer}")
        output = []
        for f in frames:
            value = reduce_values([p[1] for p in f["points"]], reducer)
            output.append(ts_frame(f["name"], [[end_ms, value]], labels=f.get("labels"), unit=f.get("unit", ""), ref_id=ref_id, meta={"reducer": reducer}))
        return output, []
    if kind == "resample":
        window = parse_duration(expr_target.get("window", "5m")) * 1000
        method = expr_target.get("downsampler", "avg")
        if method not in ("avg", "min", "max", "sum", "count", "last", "first", "median"):
            raise ExpressionError(f"Bilinmeyen örnekleme fonksiyonu: {method}")
        return [dict(f, refId=ref_id, points=bucketize(f["points"], window, method, anchor_ms)) for f in frames], []
    raise ExpressionError(f"Unknown expression type: {kind}")
