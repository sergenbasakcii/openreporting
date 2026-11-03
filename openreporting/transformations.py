"""Panel transformations (Grafana ids where semantics match).

Run on the server for the dashboard view *and* the report renderer, so a group
summary table in the browser is byte-for-byte the same table in the PDF.
"""

import re
from collections import OrderedDict

from .domain import DomainError
from .frames import REDUCERS, display_name, reduce_values, table_frame
from .safe_regex import RegexError, compile_slashed

CATALOG = [
    {"id": "reduce", "name": "Seriyi tek değere indir", "description": "Her seriyi satıra çevirir: ortalama, en yüksek, son değer… (grup özet tablosu)"},
    {
        "id": "reduceByLabel",
        "name": "Etikete göre matris (host × metrik)",
        "description": "Satırlar etiket değeri (ör. host), sütunlar metrikler; hücre seçilen hesaplama.",
    },
    {"id": "seriesToColumns", "name": "Zamana göre birleştir", "description": "Tüm zaman serilerini ortak zaman sütununda tek tabloya birleştirir."},
    {"id": "seriesToRows", "name": "Serileri satırlara çevir", "description": "Zaman, Metrik, Değer uzun format tablo."},
    {"id": "filterByName", "name": "Ada göre filtrele", "description": "Seri/sütun adını regex ile dahil et/çıkar."},
    {"id": "filterByRefId", "name": "Sorguya göre filtrele", "description": "Yalnızca seçilen sorgu sonuçlarını göster."},
    {"id": "organize", "name": "Sütunları düzenle", "description": "Sütunları gizle, yeniden adlandır, sırala."},
    {"id": "sortBy", "name": "Sırala", "description": "Tabloyu bir sütuna göre sıralar."},
    {"id": "limit", "name": "Satır sınırı", "description": "İlk N satırı tutar."},
    {"id": "calculateField", "name": "Hesaplanan sütun", "description": "Satır toplamı/ortalaması veya iki sütun arası işlem."},
    {"id": "groupingToMatrix", "name": "Gruplama matrisi", "description": "Tablo sütunlarından pivot matris üretir."},
    {"id": "renameByRegex", "name": "Regex ile yeniden adlandır", "description": "Seri adlarını düzenli ifade ile değiştirir."},
    {"id": "merge", "name": "Tabloları birleştir", "description": "Aynı sütunlara sahip tabloları tek tabloda birleştirir."},
]


class TransformationError(DomainError):
    pass


def _regex(pattern):
    if not pattern:
        return None
    try:
        return compile_slashed(pattern)
    except RegexError as exc:
        raise TransformationError(str(exc)) from exc


def _series(frames):
    return [f for f in frames if f["type"] == "timeseries"]


def _tables(frames):
    return [f for f in frames if f["type"] == "table"]


def reduce_series(frames, reducers, labels_to_fields=True):
    series = _series(frames)
    reducers = [r for r in (reducers or ["lastNotNull"]) if r in REDUCERS] or ["lastNotNull"]
    label_keys = []
    if labels_to_fields:
        for f in series:
            for key in f.get("labels") or {}:
                if key not in label_keys and not key.endswith("id") and key != "host_technical":
                    label_keys.append(key)
    units = {f.get("unit", "") for f in series}
    shared_unit = units.pop() if len(units) == 1 else ""
    columns = [{"name": "Seri", "type": "string"}]
    columns += [{"name": key, "type": "string"} for key in label_keys]
    for reducer in reducers:
        column = {"name": REDUCERS[reducer], "type": "number", "reducer": reducer}
        if shared_unit and reducer not in ("count", "nullCount", "changeCount", "distinctCount", "allIsNull", "allIsZero"):
            column["unit"] = shared_unit
        columns.append(column)
    rows, row_units = [], []
    for f in series:
        values = [p[1] for p in f["points"]]
        rows.append([display_name(f)] + [(f.get("labels") or {}).get(k, "") for k in label_keys] + [reduce_values(values, r) for r in reducers])
        row_units.append(f.get("unit", ""))
    table = table_frame("Özet", columns, rows, ref_id=series[0]["refId"] if series else "", meta={"rowUnits": row_units if not shared_unit else []})
    for column, original in zip(table["columns"], columns):
        if original.get("reducer"):
            column["reducer"] = original["reducer"]
    return [table] + [f for f in frames if f["type"] != "timeseries"]


def reduce_by_label(frames, label="host", reducer="mean", column_by="name"):
    series = _series(frames)
    if reducer not in REDUCERS:
        raise TransformationError("Unknown reducer")
    matrix = OrderedDict()
    columns = OrderedDict()
    for f in series:
        labels = f.get("labels") or {}
        row = labels.get(label, "—")
        if column_by == "refId":
            column = f.get("refId") or "?"
        elif column_by.startswith("label:"):
            column = labels.get(column_by[6:], "—")
        elif column_by == "item":
            column = labels.get("item") or display_name(f)
        else:
            column = display_name(f) if label not in labels else (labels.get("item") or display_name(f))
        columns.setdefault(column, f.get("unit", ""))
        matrix.setdefault(row, {})[column] = reduce_values([p[1] for p in f["points"]], reducer)
    header = [{"name": label, "type": "string"}] + [{"name": name, "type": "number", **({"unit": unit} if unit else {})} for name, unit in columns.items()]
    rows = [[row] + [values.get(name) for name in columns] for row, values in matrix.items()]
    return [table_frame(f"{label} × metrik", header, rows, ref_id=series[0]["refId"] if series else "", meta={"reducer": reducer})] + _tables(frames)


def series_to_columns(frames):
    series = _series(frames)
    timestamps = sorted({p[0] for f in series for p in f["points"]})
    lookups = [dict((t, v) for t, v in f["points"]) for f in series]
    columns = [{"name": "Zaman", "type": "time"}] + [
        {"name": display_name(f), "type": "number", **({"unit": f["unit"]} if f.get("unit") else {})} for f in series
    ]
    rows = [[ts] + [lookup.get(ts) for lookup in lookups] for ts in timestamps]
    return [table_frame("Birleşik", columns, rows)] + _tables(frames)


def series_to_rows(frames):
    rows = []
    for f in _series(frames):
        rows.extend([ts, display_name(f), value] for ts, value in f["points"])
    rows.sort(key=lambda r: (r[0], r[1]))
    units = {f.get("unit", "") for f in _series(frames)}
    value_column = {"name": "Değer", "type": "number"}
    if len(units) == 1 and next(iter(units)):
        value_column["unit"] = next(iter(units))
    return [table_frame("Satırlar", [{"name": "Zaman", "type": "time"}, {"name": "Metrik", "type": "string"}, value_column], rows)] + _tables(frames)


def _filter_by_name(frames, options):
    include = options.get("include")
    exclude = options.get("exclude")
    if isinstance(include, dict):
        names = set(include.get("names") or [])
        include = include.get("pattern") or ("^(" + "|".join(re.escape(n) for n in names) + ")$" if names else None)
    if isinstance(exclude, dict):
        exclude = exclude.get("pattern")
    inc, exc = _regex(include), _regex(exclude)

    def keep(name):
        return (not inc or inc.search(name)) and not (exc and exc.search(name))

    output = []
    for f in frames:
        if f["type"] == "timeseries":
            if keep(display_name(f)):
                output.append(f)
        else:
            indexes = [i for i, c in enumerate(f["columns"]) if keep(c["name"])]
            output.append(dict(f, columns=[f["columns"][i] for i in indexes], rows=[[row[i] for i in indexes] for row in f["rows"]]))
    return output


def _organize(frame, options):
    exclude = {k for k, v in (options.get("excludeByName") or {}).items() if v}
    order = options.get("indexByName") or {}
    rename = options.get("renameByName") or {}
    indexes = [i for i, c in enumerate(frame["columns"]) if c["name"] not in exclude]
    indexes.sort(key=lambda i: order.get(frame["columns"][i]["name"], 1000 + i))
    columns = [dict(frame["columns"][i], name=rename.get(frame["columns"][i]["name"]) or frame["columns"][i]["name"]) for i in indexes]
    return dict(frame, columns=columns, rows=[[row[i] for i in indexes] for row in frame["rows"]])


def _column_index(frame, name):
    for index, column in enumerate(frame["columns"]):
        if column["name"] == name:
            return index
    return None


def _sort(frame, options):
    spec = options.get("sort") or [{"field": options.get("field"), "desc": options.get("desc", False)}]
    rows = list(frame["rows"])
    for entry in reversed(spec):
        index = _column_index(frame, entry.get("field"))
        if index is None:
            continue
        desc = bool(entry.get("desc"))
        present = [r for r in rows if r[index] is not None]
        missing = [r for r in rows if r[index] is None]
        present.sort(key=lambda r: (isinstance(r[index], str), r[index]), reverse=desc)
        rows = present + missing
    return dict(frame, rows=rows)


def _calculate(frame, options):
    mode = options.get("mode", "reduceRow")
    alias = str(options.get("alias") or "Hesap")
    numeric = [i for i, c in enumerate(frame["columns"]) if c.get("type") == "number"]
    if mode == "binary":
        binary = options.get("binary") or {}
        left = _column_index(frame, binary.get("left"))
        right_name = binary.get("right")
        right = _column_index(frame, right_name)
        constant = None
        if right is None:
            try:
                constant = float(right_name)
            except (TypeError, ValueError):
                raise TransformationError("Binary calculation needs two columns or a number") from None
        op = binary.get("operator", "+")
        ops = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b, "/": lambda a, b: a / b if b else None}
        if left is None or op not in ops:
            raise TransformationError("Invalid binary calculation")
        rows = []
        for row in frame["rows"]:
            a = row[left]
            b = constant if constant is not None else row[right]
            rows.append(row + [ops[op](a, b) if a is not None and b is not None else None])
    else:
        reducer = (options.get("reduce") or {}).get("reducer", "sum")
        include = (options.get("reduce") or {}).get("include")
        cols = [i for i in numeric if not include or frame["columns"][i]["name"] in include]
        rows = [row + [reduce_values([row[i] for i in cols], reducer)] for row in frame["rows"]]
    unit = None
    if mode != "binary" or (options.get("binary") or {}).get("operator") in ("+", "-"):
        units = {frame["columns"][i].get("unit") for i in numeric}
        unit = units.pop() if len(units) == 1 else None
    column = {"name": alias, "type": "number", **({"unit": unit} if unit else {})}
    if options.get("replaceFields"):
        if not frame["columns"]:
            raise TransformationError("Hesaplanan sütun için tabloda sütun yok")
        return table_frame(frame["name"], [frame["columns"][0], column], [[row[0], row[-1]] for row in rows], ref_id=frame.get("refId", ""))
    return dict(frame, columns=frame["columns"] + [column], rows=rows)


def _grouping_matrix(frame, options):
    row_i = _column_index(frame, options.get("rowField"))
    col_i = _column_index(frame, options.get("columnField"))
    val_i = _column_index(frame, options.get("valueField"))
    if None in (row_i, col_i, val_i):
        raise TransformationError("groupingToMatrix needs existing row, column and value fields")
    matrix, columns = OrderedDict(), []
    for row in frame["rows"]:
        if row[col_i] not in columns:
            columns.append(row[col_i])
        matrix.setdefault(row[row_i], {})[row[col_i]] = row[val_i]
    unit = frame["columns"][val_i].get("unit")
    header = [{"name": f"{options.get('rowField')}\\{options.get('columnField')}", "type": "string"}] + [
        {"name": str(c), "type": "number", **({"unit": unit} if unit else {})} for c in columns
    ]
    return table_frame(frame["name"], header, [[r] + [v.get(c) for c in columns] for r, v in matrix.items()], ref_id=frame.get("refId", ""))


def apply_transformations(frames, transformations):
    current = list(frames)
    for entry in transformations or []:
        if not isinstance(entry, dict) or entry.get("disabled"):
            continue
        kind = entry.get("id")
        options = entry.get("options") or {}
        if kind == "reduce":
            if options.get("mode") == "reduceFields":
                reducer = (options.get("reducers") or ["lastNotNull"])[0]
                current = [
                    dict(f, points=[[f["points"][-1][0], reduce_values([p[1] for p in f["points"]], reducer)]] if f["points"] else [])
                    if f["type"] == "timeseries"
                    else f
                    for f in current
                ]
            else:
                current = reduce_series(current, options.get("reducers"), options.get("labelsToFields", True))
        elif kind == "reduceByLabel":
            current = reduce_by_label(current, str(options.get("label") or "host"), options.get("reducer", "mean"), str(options.get("columnBy") or "name"))
        elif kind in ("seriesToColumns", "joinByField"):
            current = series_to_columns(current)
        elif kind == "seriesToRows":
            current = series_to_rows(current)
        elif kind in ("filterByName", "filterFieldsByName"):
            current = _filter_by_name(current, options)
        elif kind == "filterByRefId":
            pattern = _regex(options.get("include"))
            current = [f for f in current if not pattern or pattern.fullmatch(f.get("refId") or "")]
        elif kind == "organize":
            current = [_organize(f, options) if f["type"] == "table" else f for f in current]
        elif kind == "sortBy":
            current = [_sort(f, options) if f["type"] == "table" else f for f in current]
        elif kind == "limit":
            limit = max(0, int(options.get("limitField", options.get("limit", 10)) or 0))
            current = [dict(f, rows=f["rows"][:limit]) if f["type"] == "table" else f for f in current]
        elif kind == "calculateField":
            current = [_calculate(f, options) if f["type"] == "table" else f for f in current]
        elif kind == "groupingToMatrix":
            current = [_grouping_matrix(f, options) if f["type"] == "table" else f for f in current]
        elif kind == "renameByRegex":
            pattern = _regex(options.get("regex"))
            replacement = re.sub(r"\$(\d+)", r"\\\1", str(options.get("renamePattern", "")))
            if pattern:
                current = [
                    dict(f, name=pattern.sub(replacement, display_name(f)), meta={**(f.get("meta") or {}), "displayName": None})
                    if f["type"] == "timeseries"
                    else f
                    for f in current
                ]
        elif kind == "merge":
            tables = _tables(current)
            if len(tables) > 1:
                names = [c["name"] for c in tables[0]["columns"]]
                merged = [t for t in tables if [c["name"] for c in t["columns"]] == names]
                rest = [t for t in tables if t not in merged]
                rows = [row for t in merged for row in t["rows"]]
                current = _series(current) + [dict(tables[0], rows=rows)] + rest
        else:
            raise TransformationError(f"Unknown transformation: {kind}")
    return current
