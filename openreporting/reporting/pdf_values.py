"""Single-value and categorical drawing (stat, gauge, bars, pie, grids, text, narrative)."""

import math
from .compare import comparison_deltas, delta_text
from .narrative import sentences as narrative_sentences
from .fieldcfg import contrast, display_name, field_config, fmt, mapped, options, reduced_items, series_color, threshold_color, color as named_color
from .pdf_base import (
    INK,
    MUTED,
    FAINT,
    BRAND,
    STAT_MIN_W,
    STAT_MIN_H,
    _rgb,
)


class ValuesMixin:
    def _grid(self, count, w, h):
        cols = max(1, min(count, round(math.sqrt(count * (w / max(1, h))))))
        rows = math.ceil(count / cols)
        return cols, rows

    def draw_stat(self, panel, frames, x, y, w, h):
        items = reduced_items(panel, frames)
        if not items:
            self.text(x + w / 2, y + h / 2, "Veri yok", 10, FAINT, align="center")
            return
        deltas = comparison_deltas(panel, frames, items)
        color_mode = options(panel, "colorMode", "value")
        graph = options(panel, "graphMode", "area")
        text_mode = options(panel, "textMode", "auto")
        # Each value needs a readable cell; beyond that the rest is summarised instead of overprinted.
        capacity = max(1, int(w // STAT_MIN_W) * int(h // STAT_MIN_H))
        hidden = 0
        if len(items) > capacity:
            hidden = len(items) - (capacity - 1)
            items = items[: capacity - 1]
        cols, rows = self._grid(len(items) + (1 if hidden else 0), w, h)
        cw, ch = w / cols, h / rows
        for index, item in enumerate(items):
            col, row = index % cols, index // cols
            cx, cy = x + col * cw, y + h - (row + 1) * ch
            hit = mapped(item["value"], item["cfg"].get("mappings"))
            colr = named_color(hit["color"]) if hit and hit.get("color") else item["color"]
            text_color = colr if color_mode == "value" else INK
            if color_mode in ("background", "background_solid"):
                self.c.setFillColor(_rgb(colr))
                self.c.roundRect(cx + 1.5, cy + 1.5, cw - 3, ch - 3, 3, stroke=0, fill=1)
                text_color = contrast(colr)
            if graph == "area" and len(item["points"]) > 1 and ch > 40:
                self._sparkline(item["points"], cx + 2, cy + 2, cw - 4, ch * 0.35, "#ffffff" if color_mode.startswith("background") else colr)
            show_name = text_mode in ("value_and_name", "name") or (text_mode == "auto" and len(items) > 1)
            value_text = fmt(item["value"], item["cfg"], item["unit"])
            size = max(8, min(30, ch * 0.42, (cw - 8) / max(1, len(value_text)) * 1.7))
            center_y = cy + ch / 2 - size / 3 + (4 if show_name else 0)
            if show_name:
                self.text(
                    cx + cw / 2, cy + ch - 11, item["name"], 7, text_color if color_mode.startswith("background") else MUTED, max_width=cw - 6, align="center"
                )
            if text_mode != "name":
                self.text(cx + cw / 2, center_y, value_text, size, text_color, bold=True, align="center", max_width=cw - 4)
            delta = deltas.get(index)
            if delta is not None and ch > 34:
                label, tone = delta_text(delta, options(panel, "compareGood", "neutral"))
                dcolor = {"good": "#15803d", "bad": "#be123c"}.get(tone, MUTED)
                self.text(
                    cx + cw / 2,
                    max(cy + 4, center_y - size * 0.55 - 2),
                    label,
                    7,
                    dcolor if not color_mode.startswith("background") else text_color,
                    bold=True,
                    align="center",
                    max_width=cw - 4,
                )
        if hidden:
            index = len(items)
            col, row = index % cols, index // cols
            cx, cy = x + col * cw, y + h - (row + 1) * ch
            self.text(cx + cw / 2, cy + ch / 2 + 2, f"+{hidden} değer daha", 8, MUTED, bold=True, align="center", max_width=cw - 4)
            self.text(cx + cw / 2, cy + ch / 2 - 9, "tam liste Excel/CSV’de", 6.5, FAINT, align="center", max_width=cw - 4)

    def _sparkline(self, points, x, y, w, h, colr):
        values = [(t, v) for t, v in points if v is not None]
        if len(values) < 2:
            return
        t0, t1 = values[0][0], values[-1][0]
        vs = [v for _, v in values]
        lo, hi = min(vs), max(vs)
        coords = [(x + (t - t0) / (t1 - t0 or 1) * w, y + (v - lo) / (hi - lo or 1) * h) for t, v in values]
        if len(coords) > w:
            step = math.ceil(len(coords) / w)
            coords = coords[::step]
        path = self.c.beginPath()
        path.moveTo(coords[0][0], y)
        for point in coords:
            path.lineTo(*point)
        path.lineTo(coords[-1][0], y)
        path.close()
        self.c.setFillColor(_rgb(colr, 0.22))
        self.c.drawPath(path, stroke=0, fill=1)
        line = self.c.beginPath()
        line.moveTo(*coords[0])
        for point in coords[1:]:
            line.lineTo(*point)
        self.c.setStrokeColor(_rgb(colr, 0.85))
        self.c.setLineWidth(0.7)
        self.c.drawPath(line, stroke=1, fill=0)

    def draw_gauge(self, panel, frames, x, y, w, h):
        items = reduced_items(panel, frames)
        if not items:
            return
        cols, rows = self._grid(len(items), w, h)
        cw, ch = w / cols, h / rows
        c = self.c
        for index, item in enumerate(items):
            col, row = index % cols, index // cols
            cfg = item["cfg"]
            low = float(cfg.get("min") if cfg.get("min") is not None else 0)
            high = float(cfg.get("max") if cfg.get("max") is not None else (100 if item["unit"] == "percent" else max(100, (item["value"] or 0) * 1.2)))
            radius = max(8, min(cw * 0.42, ch * 0.5))
            cx = x + col * cw + cw / 2
            cy = y + h - row * ch - ch / 2 - radius * 0.12
            thickness = max(3, radius * 0.18)
            box = (cx - radius, cy - radius, cx + radius, cy + radius)
            c.setLineCap(0)
            steps = ((cfg.get("thresholds") or {}).get("steps")) or [{"color": "green", "value": None}]
            outer = (cx - radius - thickness * 0.9, cy - radius - thickness * 0.9, cx + radius + thickness * 0.9, cy + radius + thickness * 0.9)
            for i, step in enumerate(steps):
                start = low if step.get("value") is None else float(step["value"])
                end = high if i + 1 >= len(steps) else float(steps[i + 1]["value"])
                if (cfg.get("thresholds") or {}).get("mode") == "percentage":
                    start = low + (high - low) * (0 if step.get("value") is None else float(step["value"])) / 100
                    end = high if i + 1 >= len(steps) else low + (high - low) * float(steps[i + 1]["value"]) / 100
                f0 = max(0, min(1, (start - low) / (high - low or 1)))
                f1 = max(0, min(1, (end - low) / (high - low or 1)))
                if f1 <= f0:
                    continue
                path = c.beginPath()
                path.arc(*outer, startAng=210 - 240 * f0, extent=-240 * (f1 - f0))
                c.setStrokeColor(_rgb(step.get("color")))
                c.setLineWidth(max(1.2, thickness * 0.3))
                c.drawPath(path, stroke=1, fill=0)
            path = c.beginPath()
            path.arc(*box, startAng=210, extent=-240)
            c.setStrokeColor(_rgb("#e6e9ef"))
            c.setLineWidth(thickness)
            c.drawPath(path, stroke=1, fill=0)
            value = item["value"]
            if value is not None:
                frac = max(0, min(1, (value - low) / (high - low or 1)))
                if frac > 0:
                    path = c.beginPath()
                    path.arc(*box, startAng=210, extent=-240 * frac)
                    c.setStrokeColor(_rgb(threshold_color(value, cfg.get("thresholds"), low, high) or item["color"]))
                    c.setLineWidth(thickness)
                    c.drawPath(path, stroke=1, fill=0)
            text = fmt(value, cfg, item["unit"])
            size = max(7, min(22, radius * 0.45, (radius * 1.6) / max(1, len(text)) * 1.7))
            self.text(cx, cy - size * 0.3, text, size, threshold_color(value, cfg.get("thresholds"), low, high) or INK, bold=True, align="center")
            if len(items) > 1 or ch > radius * 2.2:
                self.text(cx, cy - radius * 0.78, item["name"], 6.5, MUTED, align="center", max_width=cw - 6)

    def draw_bars(self, panel, frames, x, y, w, h, kind):
        items = reduced_items(panel, frames)
        if options(panel, "sort", "none") == "desc":
            items.sort(key=lambda i: (i["value"] is None, -(i["value"] or 0)))
        elif options(panel, "sort", "none") == "asc":
            items.sort(key=lambda i: (i["value"] is None, i["value"] or 0))
        if not items:
            return
        row_h = max(9, min(22, h / len(items)))
        visible = items[: max(1, int(h // row_h))]
        name_w = min(w * 0.32, max(self.width(i["name"], 7) for i in visible) + 6)
        value_w = 58
        bar_w = w - name_w - value_w - 6
        values = [i["value"] for i in visible if i["value"] is not None]
        for index, item in enumerate(visible):
            cfg = item["cfg"]
            low = float(cfg.get("min") if cfg.get("min") is not None else 0)
            high = float(cfg.get("max") if cfg.get("max") is not None else (100 if item["unit"] == "percent" else max(values or [1]) or 1))
            yy = y + h - (index + 1) * row_h
            self.text(x, yy + row_h / 2 - 2.5, item["name"], 7, INK, max_width=name_w - 4)
            self.c.setFillColor(_rgb("#eef0f4"))
            self.c.rect(x + name_w, yy + row_h * 0.18, bar_w, row_h * 0.64, stroke=0, fill=1)
            if item["value"] is not None:
                frac = max(0, min(1, (item["value"] - low) / (high - low or 1)))
                colr = item["color"] if kind == "bargauge" else (item["color"] if (cfg.get("color") or {}).get("mode") == "thresholds" else item["color"])
                self.c.setFillColor(_rgb(colr))
                self.c.rect(x + name_w, yy + row_h * 0.18, max(0.5, bar_w * frac), row_h * 0.64, stroke=0, fill=1)
            self.text(x + w, yy + row_h / 2 - 2.5, fmt(item["value"], cfg, item["unit"]), 7.5, INK, bold=True, align="right")
        if len(visible) < len(items):
            self.text(x + w, y - 1, f"+{len(items) - len(visible)} değer daha", 6, FAINT, align="right")

    def draw_pie(self, panel, frames, x, y, w, h):
        items = [i for i in reduced_items(panel, frames) if i["value"] not in (None, 0)]
        total = sum(abs(i["value"]) for i in items)
        if not items or not total:
            self.text(x + w / 2, y + h / 2, "Veri yok", 10, FAINT, align="center")
            return
        legend_w = min(w * 0.55, 190) if w > 160 else 0
        radius = max(10, min((w - legend_w) / 2 - 6, h / 2 - 4))
        cx, cy = x + (w - legend_w) / 2, y + h / 2
        angle = 90.0
        for index, item in enumerate(items):
            extent = -360 * abs(item["value"]) / total
            colr = (
                item["color"]
                if (item["cfg"].get("color") or {}).get("mode") == "thresholds"
                else series_color({"color": {"mode": "palette-classic"}}, index, None)
            )
            item["_color"] = colr
            self.c.setFillColor(_rgb(colr))
            self.c.setStrokeColor(_rgb("#ffffff"))
            self.c.setLineWidth(0.6)
            self.c.wedge(cx - radius, cy - radius, cx + radius, cy + radius, angle, extent, stroke=1, fill=1)
            angle += extent
        if options(panel, "pieType", "pie") == "donut":
            self.c.setFillColor(_rgb("#ffffff"))
            self.c.circle(cx, cy, radius * 0.55, stroke=0, fill=1)
        if legend_w:
            line_y = y + h - 9
            for item in items[: max(1, int(h // 10))]:
                self.c.setFillColor(_rgb(item["_color"]))
                self.c.rect(x + w - legend_w, line_y + 1, 7, 5, stroke=0, fill=1)
                pct = abs(item["value"]) / total * 100
                value_text = f"{pct:.1f}%" if legend_w < 150 else f"{fmt(item['value'], item['cfg'], item['unit'])} · {pct:.1f}%"
                value_w = self.width(value_text, 6.8) + 6
                self.text(x + w - legend_w + 10, line_y, item["name"], 6.8, INK, max_width=legend_w - value_w - 12)
                self.text(x + w, line_y, value_text, 6.8, MUTED, align="right")
                line_y -= 10

    def draw_statusgrid(self, panel, frames, x, y, w, h):
        items = reduced_items(panel, frames)
        field = options(panel, "labelField", "host")
        if options(panel, "sort", "name") == "name":
            items.sort(key=lambda i: str(i["labels"].get(field) or i["name"]))
        elif options(panel, "sort", "name") == "value":
            items.sort(key=lambda i: (i["value"] is None, -(i["value"] or 0)))
        min_w = 82
        cols = max(1, int(w // min_w))
        rows = math.ceil(len(items) / cols)
        cell_h = max(16, min(34, h / max(1, rows)))
        cell_w = w / cols
        fit = int(h // cell_h) * cols
        for index, item in enumerate(items[:fit]):
            col, row = index % cols, index // cols
            cx, cy = x + col * cell_w, y + h - (row + 1) * cell_h
            colr = "#bcc3cf" if item["value"] is None else item["color"]
            self.c.setFillColor(_rgb(colr))
            self.c.roundRect(cx + 1.2, cy + 1.2, cell_w - 2.4, cell_h - 2.4, 2, stroke=0, fill=1)
            label = item["labels"].get(field) or item["name"]
            ink = contrast(colr)
            self.text(cx + 5, cy + cell_h - 10, label, 6.8, ink, bold=True, max_width=cell_w - 9)
            if options(panel, "showValue", True) is not False and cell_h > 22:
                self.text(cx + 5, cy + 5, fmt(item["value"], item["cfg"], item["unit"]), 8, ink, max_width=cell_w - 9)
        if len(items) > fit:
            self.text(x + w, y - 1, f"+{len(items) - fit} host daha", 6, FAINT, align="right")

    def draw_state_timeline(self, panel, frames, x, y, w, h):
        series = [f for f in frames if f["type"] == "timeseries"]
        start = self.collected.start.timestamp() * 1000
        end = self.collected.end.timestamp() * 1000
        row_h = max(8, min(20, (h - 10) / max(1, len(series))))
        name_w = min(w * 0.28, 130)
        for index, frame in enumerate(series[: int((h - 10) // row_h)]):
            name = display_name(frame)
            cfg = field_config(panel, frame, name)
            yy = y + h - (index + 1) * row_h
            self.text(x, yy + row_h / 2 - 2.5, name, 6.8, INK, max_width=name_w - 4)
            points = frame["points"]
            for i, (ts, value) in enumerate(points):
                nxt = points[i + 1][0] if i + 1 < len(points) else end
                x0 = x + name_w + (max(ts, start) - start) / (end - start or 1) * (w - name_w)
                x1 = x + name_w + (min(nxt, end) - start) / (end - start or 1) * (w - name_w)
                hit = mapped(value, cfg.get("mappings"))
                colr = (
                    "#d4d8e0"
                    if value is None
                    else (
                        named_color(hit["color"])
                        if hit and hit.get("color")
                        else threshold_color(value, cfg.get("thresholds"), cfg.get("min") or 0, cfg.get("max") or 100)
                    )
                )
                self.c.setFillColor(_rgb(colr or "#5794F2"))
                self.c.rect(x0, yy + row_h * 0.15, max(0.3, x1 - x0), row_h * 0.7, stroke=0, fill=1)

    def draw_narrative(self, panel, frames, x, y, w, h):
        lines = narrative_sentences(panel, frames or [], self.collected.timezone)
        if not lines:
            self.text(x + w / 2, y + h / 2, "Özet için veri yok", 9, FAINT, align="center")
            return
        line_y = y + h - 10
        for sentence in lines:
            wrapped = self.wrap(sentence, 8.5, w - 14)
            for i, line in enumerate(wrapped):
                if line_y < y + 4:
                    return
                if i == 0:
                    self.c.setFillColor(_rgb(BRAND))
                    self.c.circle(x + 4, line_y + 2.6, 1.6, stroke=0, fill=1)
                self.text(x + 11, line_y, line, 8.5, INK)
                line_y -= 11
            line_y -= 3

    def draw_text(self, panel, x, y, w, h):
        content = (panel.get("options") or {}).get("content", "")
        line_y = y + h - 9
        for raw in str(content).replace("\r", "").split("\n"):
            line = raw.strip()
            if not line or line.startswith("```"):
                line_y -= 4
                continue
            size, bold, indent = 8, False, 0
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                line = line.lstrip("#").strip()
                size, bold = max(9, 14 - level * 1.5), True
            elif line[:2] in ("- ", "* "):
                line, indent = "• " + line[2:], 6
            clean = line.replace("**", "").replace("`", "")
            for wrapped in self.wrap(clean, size, w - indent - 4, bold):
                if line_y < y:
                    return
                self.text(x + indent, line_y, wrapped, size, INK, bold=bold)
                line_y -= size + 3

    # tables -------------------------------------------------------------------
