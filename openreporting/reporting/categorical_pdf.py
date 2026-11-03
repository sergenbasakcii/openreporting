"""Vector rendering for categorical and multivariate report panels."""

import math
from collections import OrderedDict

from reportlab.lib.colors import HexColor

from .extended_pdf import numeric, table_data
from .fieldcfg import SERIES as PALETTE  # same brand series as the other report charts
from .fieldcfg import contrast, reduced_items

TYPES = {"waterfall", "funnel", "treemap", "sunburst", "rosepie", "parallel"}


def waterfall_steps(values):
    total, steps = 0, []
    for value in values:
        start = total
        total += value
        steps.append((start, total))
    return steps


def proportional_widths(values, width):
    total = sum(values)
    return [width * value / total for value in values] if total else [0] * len(values)


def draw(pdf, panel, frames, x, y, w, h):
    kind = panel.get("type")
    if kind not in TYPES:
        return False
    c = pdf.c

    def message(text):
        pdf.text(x, y + h / 2, text, 7, max_width=w)

    if w < 100 or h < 65:
        message("Grafik için paneli büyütün")
        return True
    if sum(len(f.get("rows", f.get("points", []))) for f in frames) > 100000:
        message("Grafik için sorguyu 100.000 satır/nokta altına daraltın")
        return True
    left, bottom, width, height = x + 30, y + 22, w - 44, h - 36

    def polygon(points, color):
        path = c.beginPath()
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        path.close()
        c.setFillColor(HexColor(color))
        c.setStrokeColor(HexColor("#ffffff"))
        c.setLineWidth(0.5)
        c.drawPath(path, stroke=1, fill=1)

    if kind == "parallel":
        table, columns = table_data(frames)
        if table is None or len(columns) < 2:
            message("En az iki sayısal sütun içeren tablo gerekir")
            return True
        rows = [row for row in table["rows"] if all(numeric(row[i]) for i in columns)]
        if not rows:
            message("Veri yok")
            return True
        if len(rows) * len(columns) > 100000:
            message("Paralel grafik için satır/sütun sayısını azaltın")
            return True
        extents = [(min(0, min(row[i] for row in rows)), max(0, max(row[i] for row in rows))) for i in columns]
        gap = width / (len(columns) - 1)
        c.setStrokeColor(HexColor("#c9ced8"))
        c.setLineWidth(0.5)
        for dim, (index, (low, high)) in enumerate(zip(columns, extents)):
            xx = left + dim * gap
            c.line(xx, bottom, xx, bottom + height)
            pdf.text(xx, y + 6, table["columns"][index]["name"], 6, align="center", max_width=max(4, gap - 4))
            pdf.text(xx, bottom + height + 4, f"{high:.4g}", 6, align="center")
            pdf.text(xx, bottom - 9, f"{low:.4g}", 6, align="center")
        for n, row in enumerate(rows):
            path = c.beginPath()
            for dim, (index, (low, high)) in enumerate(zip(columns, extents)):
                point = (left + dim * gap, bottom + (row[index] - low) / (high - low or 1) * height)
                (path.moveTo if dim == 0 else path.lineTo)(*point)
            c.setStrokeColor(HexColor(PALETTE[n % len(PALETTE)]))
            c.setLineWidth(0.6)
            c.drawPath(path, stroke=1, fill=0)
        return True

    items = [item for item in reduced_items(panel, frames) if numeric(item["value"])]
    if not items:
        message("Veri yok")
        return True
    if kind != "waterfall" and any(item["value"] < 0 for item in items):
        message("Bu grafik negatif değerleri desteklemez")
        return True
    values = [item["value"] for item in items]
    if kind == "waterfall":
        steps = waterfall_steps(values)
        low = min(0, min(min(pair) for pair in steps))
        high = max(0, max(max(pair) for pair in steps))
        sy = lambda value: bottom + (value - low) / (high - low or 1) * height
        c.setStrokeColor(HexColor("#c9ced8"))
        c.setLineWidth(0.5)
        c.line(left, sy(0), left + width, sy(0))
        gap = width / len(items)
        for i, (item, (start, end)) in enumerate(zip(items, steps)):
            xx = left + i * gap
            c.setFillColor(HexColor("#228c56" if end >= start else "#c73a4d"))
            c.rect(xx + gap * 0.15, min(sy(start), sy(end)), gap * 0.7, max(0.4, abs(sy(end) - sy(start))), stroke=0, fill=1)
            pdf.text(xx + gap / 2, y + 6, item["name"], 6, align="center", max_width=max(4, gap - 3))
            pdf.text(xx + gap / 2, min(bottom + height - 7, max(bottom + 2, sy(end) + 3)), f"{item['value']:.4g}", 6, align="center", max_width=max(4, gap - 3))
            if i + 1 < len(items):
                c.line(xx + gap * 0.85, sy(end), xx + gap * 1.15, sy(end))
        pdf.text(left - 3, bottom - 2, f"{low:.4g}", 6, align="right")
        pdf.text(left - 3, bottom + height - 2, f"{high:.4g}", 6, align="right")
        return True
    total = sum(values)
    if total == 0:
        message("Değerlerin toplamı sıfır")
        return True
    if kind == "funnel":
        items.sort(key=lambda item: item["value"], reverse=True)
        maximum = items[0]["value"]
        row_h = height / len(items)
        center = left + width / 2
        for i, item in enumerate(items):
            top = bottom + height - i * row_h
            top_w = width * item["value"] / maximum
            bottom_w = width * items[i + 1]["value"] / maximum if i + 1 < len(items) else 0
            col = PALETTE[i % len(PALETTE)]
            polygon([(center - top_w / 2, top), (center + top_w / 2, top), (center + bottom_w / 2, top - row_h), (center - bottom_w / 2, top - row_h)], col)
            pdf.text(
                center,
                top - row_h * 0.5,
                f"{item['name']} · {item['value']:.4g}",
                6,
                contrast(col),
                align="center",
                max_width=max(4, (top_w + bottom_w) / 2 - 4),
            )
        return True
    if kind == "treemap":
        # A slice treemap: rectangle area stays exactly proportional to value.
        xx = left
        for i, (item, cell_w) in enumerate(zip(items, proportional_widths(values, width))):
            col = PALETTE[i % len(PALETTE)]
            c.setFillColor(HexColor(col))
            c.setStrokeColor(HexColor("#ffffff"))
            c.rect(xx, bottom, cell_w, height, stroke=1, fill=1)
            if cell_w >= 8:
                pdf.text(xx + cell_w / 2, bottom + height / 2, item["name"], 6, contrast(col), align="center", max_width=cell_w - 4)
                pdf.text(xx + cell_w / 2, bottom + height / 2 - 10, f"{item['value']:.4g}", 6, contrast(col), align="center", max_width=cell_w - 4)
            xx += cell_w
        return True

    legend_w = min(width * 0.4, 170) if kind == "rosepie" and len(items) * 10 <= height else 0
    radius = min(width - legend_w, height) / 2
    center_x, center_y = left + (width - legend_w) / 2, bottom + height / 2

    def wedge(start, extent, r, color):
        c.setFillColor(HexColor(color))
        c.setStrokeColor(HexColor("#ffffff"))
        c.setLineWidth(0.5)
        c.wedge(center_x - r, center_y - r, center_x + r, center_y + r, start, extent, stroke=1, fill=1)

    if kind == "rosepie":
        angle, extent = 90, -360 / len(items)
        maximum = max(values)
        for i, item in enumerate(items):
            r = radius * item["value"] / maximum
            if r:
                wedge(angle, extent, r, PALETTE[i % len(PALETTE)])
            if legend_w:
                yy = bottom + height - i * 10 - 8
                c.setFillColor(HexColor(PALETTE[i % len(PALETTE)]))
                c.rect(left + width - legend_w, yy, 6, 6, stroke=0, fill=1)
                pdf.text(left + width - legend_w + 10, yy, f"{item['name']} · {item['value']:.4g}", 6, max_width=legend_w - 12)
            angle += extent
        if not legend_w:
            pdf.text(left, bottom - 12, "Etiket ve değerler: Excel/CSV çıktısı", 6, max_width=width)
        return True
    groups = OrderedDict()
    for item in items:
        group = str(next(iter((item.get("labels") or {}).values()), "Veriler"))
        groups.setdefault(group, []).append(item)
    angle = 90
    for group_index, (group, children) in enumerate(groups.items()):
        start = angle
        for child_index, item in enumerate(children):
            extent = -360 * item["value"] / total
            if extent:
                wedge(angle, extent, radius, PALETTE[(group_index + child_index) % len(PALETTE)])
            angle += extent
        if angle != start:
            col = PALETTE[group_index % len(PALETTE)]
            wedge(start, angle - start, radius * 0.5, col)
            middle = math.radians((start + angle) / 2)
            pdf.text(
                center_x + math.cos(middle) * radius * 0.3,
                center_y + math.sin(middle) * radius * 0.3,
                group,
                6,
                contrast(col),
                align="center",
                max_width=radius * 0.4,
            )
    return True
