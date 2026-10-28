"""Vector PDF counterparts for distribution, XY and OHLC visualizations."""
import math

from reportlab.lib.colors import HexColor

TYPES = {"histogram", "scatter", "bubble", "boxplot", "candlestick"}
BLUE, GRID, GREEN, RED = "#5794f2", "#d7dce3", "#228c56", "#c73a4d"


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def histogram(values, bins=10):
    values = [value for value in values if numeric(value)]
    if not values:
        return [], []
    try:
        bins = max(1, min(50, int(bins)))
    except (ValueError, TypeError, OverflowError):
        bins = 10
    low, high = min(values), max(values)
    width = (high - low) / bins or 1
    counts = [0] * bins
    for value in values:
        counts[min(bins - 1, math.floor((value - low) / width))] += 1
    return [low + i * width for i in range(bins + 1)], counts


def quantile(values, fraction):
    position = (len(values) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def table_data(frames):
    table = next((f for f in frames if f["type"] == "table"), None)
    if table is None:
        return None, []
    return table, [i for i, col in enumerate(table["columns"]) if col["type"] == "number"]


def draw(pdf, panel, frames, x, y, w, h):
    kind = panel.get("type")
    if kind not in TYPES:
        return False
    c = pdf.c
    if w < 100 or h < 65:
        pdf.text(x, y + h / 2, "Grafik için paneli büyütün", 7)
        return True
    count = sum(len(f["rows"] if f["type"] == "table" else f.get("points", [])) for f in frames)
    if count > 100000:
        pdf.text(x, y + h / 2, "Grafik için sorguyu 100.000 satır/nokta altına daraltın", 7, max_width=w)
        return True
    px, py, pw, ph = x + 37, y + 23, w - 49, h - 36
    table, columns = table_data(frames)
    series = [f for f in frames if f["type"] == "timeseries"]

    def message(text):
        pdf.text(x, y + h / 2, text, 7, max_width=w)

    def axes(low, high, xlow=0, xhigh=1):
        if high <= low:
            high = low + 1
        if xhigh <= xlow:
            xhigh = xlow + 1
        c.setStrokeColor(HexColor(GRID))
        c.setLineWidth(.5)
        for i in range(5):
            yy = py + ph * i / 4
            c.line(px, yy, px + pw, yy)
            pdf.text(px - 5, yy - 2, f"{low + (high-low)*i/4:.4g}", 6, align="right")
        return (lambda value: px + (value-xlow)/(xhigh-xlow)*pw,
                lambda value: py + (value-low)/(high-low)*ph)

    if kind == "histogram":
        values = [p[1] for f in series for p in f["points"]]
        if not values and table:
            values = [row[i] for row in table["rows"] for i in columns]
        edges, counts = histogram(values, (panel.get("options") or {}).get("bins", 10))
        if not counts:
            message("Veri yok")
            return True
        sx, sy = axes(0, max(counts) or 1, edges[0], edges[-1])
        c.setFillColor(HexColor(BLUE))
        for left, right, count in zip(edges, edges[1:], counts):
            c.rect(sx(left), py, max(.1, sx(right)-sx(left)-.5), sy(count)-py, stroke=0, fill=1)
        for edge in (edges[0], edges[-1]):
            pdf.text(sx(edge), y + 7, f"{edge:.4g}", 6, align="center")
        return True

    if kind in ("scatter", "bubble", "candlestick"):
        needed = 4 if kind == "candlestick" else 2
        if table is None or len(columns) < needed:
            message("Tablo gerekir: OHLC için 4, XY için 2 sayısal sütun")
            return True
        used = columns[:4 if kind == "candlestick" else 3 if kind == "bubble" else 2]
        rows = [row for row in table["rows"] if all(numeric(row[i]) for i in used)]
        if not rows:
            message("Veri yok")
            return True
        if kind == "candlestick":
            values = [[row[i] for i in used] for row in rows]
            if any(low > min(op, close) or high < max(op, close) for op, close, low, high in values):
                message("OHLC düşük/yüksek aralıklarını kontrol edin")
                return True
            _, sy = axes(min(v[2] for v in values), max(v[3] for v in values))
            cell = pw / len(rows)
            label = next((i for i, col in enumerate(table["columns"]) if col["type"] != "number"), None)
            for i, (row, (op, close, low, high)) in enumerate(zip(rows, values)):
                xx = px + (i + .5) * cell
                color = HexColor(GREEN if close >= op else RED)
                c.setStrokeColor(color)
                c.setFillColor(color)
                c.line(xx, sy(low), xx, sy(high))
                c.rect(xx-cell*.3, min(sy(op), sy(close)), cell*.6, max(.6, abs(sy(close)-sy(op))), stroke=1, fill=1)
                pdf.text(xx, y + 7, str(row[label]) if label is not None else str(i+1), 6, align="center", max_width=max(4, cell-2))
        else:
            xs, ys = [r[used[0]] for r in rows], [r[used[1]] for r in rows]
            sx, sy = axes(min(0, min(ys)), max(0, max(ys)), min(0, min(xs)), max(0, max(xs)))
            c.setFillColor(HexColor(BLUE))
            for row in rows:
                radius = 2
                if kind == "bubble":
                    size = row[used[2]] if len(used) > 2 else 1
                    radius = max(2.5, min(10, math.sqrt(abs(size))*1.5))
                c.circle(sx(row[used[0]]), sy(row[used[1]]), radius, stroke=0, fill=1)
            pdf.text(px + pw/2, y + 6, table["columns"][used[0]]["name"], 6, align="center", max_width=pw)
        return True

    groups = [(f["name"], [p[1] for p in f["points"] if numeric(p[1])]) for f in series]
    if not series and table:
        groups = [(table["columns"][i]["name"], [r[i] for r in table["rows"] if numeric(r[i])]) for i in columns]
    groups = [(name, sorted(values)) for name, values in groups if values]
    if not groups:
        message("Veri yok")
        return True
    _, sy = axes(min(v[0] for _, v in groups), max(v[-1] for _, v in groups))
    cell = pw / len(groups)
    for i, (name, values) in enumerate(groups):
        xx = px + (i+.5)*cell
        q1, median, q3 = (quantile(values, p) for p in (.25, .5, .75))
        c.setStrokeColor(HexColor(BLUE))
        c.setFillColor(HexColor("#e3edff"))
        c.line(xx, sy(values[0]), xx, sy(values[-1]))
        c.rect(xx-cell*.3, sy(q1), cell*.6, max(.5, sy(q3)-sy(q1)), stroke=1, fill=1)
        for value in (values[0], median, values[-1]):
            c.line(xx-cell*.3, sy(value), xx+cell*.3, sy(value))
        pdf.text(xx, y + 7, name, 6, align="center", max_width=max(4, cell-2))
    return True
