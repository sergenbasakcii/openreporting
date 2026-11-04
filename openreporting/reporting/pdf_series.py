"""Time-series drawing (lines, bars, legend) for the Pdf renderer."""

import math
from datetime import datetime, timezone
from ..frames import REDUCERS, reduce_values
from ..units import format_value, resolve_unit
from .fieldcfg import display_name, field_config, options, series_color
from .pdf_base import (
    INK,
    MUTED,
    FAINT,
    GRID,
    SHORT_CALCS,
    TIME_STEPS,
    _rgb,
    _nice_ticks,
)


class SeriesMixin:
    def draw_timeseries(self, panel, frames, x, y, w, h):
        series = [f for f in frames if f["type"] == "timeseries"]
        legend_mode = "hidden" if options(panel, "legend.showLegend", True) is False else options(panel, "legend.displayMode", "list")
        calcs = options(panel, "legend.calcs", []) or []
        entries = []
        stack_mode = ((((panel.get("fieldConfig") or {}).get("defaults") or {}).get("custom") or {}).get("stacking") or {}).get("mode", "none")
        stack_base = {}
        for index, frame in enumerate(series):
            name = display_name(frame)
            cfg = field_config(panel, frame, name)
            custom = cfg.get("custom") or {}
            if (custom.get("hideFrom") or {}).get("viz"):
                continue
            unit = resolve_unit(cfg.get("unit"), frame.get("unit"))
            values = [p[1] for p in frame["points"]]
            last = reduce_values(values, "lastNotNull")
            negative = custom.get("transform") == "negative-Y"
            points = []
            for ts, value in frame["points"]:
                if value is None:
                    points.append((ts, None))
                    continue
                v = -value if negative else value
                if stack_mode == "normal":
                    key = (ts, negative)
                    v += stack_base.get(key, 0)
                    stack_base[key] = v
                points.append((ts, v))
            entries.append(
                {
                    "name": cfg.get("displayName") or name,
                    "color": series_color(cfg, index, last),
                    "unit": unit,
                    "cfg": cfg,
                    "points": points,
                    "values": values,
                    "negative": negative,
                    "draw": custom.get("drawStyle", "line"),
                    "fill": custom.get("fillOpacity", 10),
                    "width": custom.get("lineWidth", 1),
                    "span": custom.get("spanNulls", False),
                    "step": custom.get("lineInterpolation") == "stepAfter",
                    "previous": bool((frame.get("meta") or {}).get("previous")),
                }
            )
            if entries[-1]["previous"]:
                entries[-1]["fill"] = 0
        if not entries:
            self.text(x + w / 2, y + h / 2, "Veri yok", 10, FAINT, align="center")
            return
        legend_h = 0
        if legend_mode != "hidden":
            rows = len(entries) + (1 if legend_mode == "table" or calcs else 0)
            per_line = 1 if legend_mode == "table" or calcs else max(1, int(w // 150))
            legend_h = min(h * 0.38, math.ceil(rows / per_line) * 9.5 + 3)
        plot_bottom = y + legend_h + 12
        plot_h = h - legend_h - 16
        if plot_h < 20:
            plot_h, legend_h, plot_bottom = h - 16, 0, y + 12
        all_values = [v for e in entries for _, v in e["points"] if v is not None]
        start_ms = self.collected.start.timestamp() * 1000
        end_ms = self.collected.end.timestamp() * 1000
        times = [t for e in entries for t, _ in e["points"]]
        if times:
            start_ms, end_ms = min(start_ms, min(times)), max(end_ms, max(times))
        if not all_values:
            self.text(x + w / 2, y + h / 2, "Veri yok", 10, FAINT, align="center")
            return
        cfg0 = entries[0]["cfg"]
        low, high = min(all_values), max(all_values)
        if cfg0.get("min") is not None:
            low = float(cfg0["min"])
        if cfg0.get("max") is not None:
            high = float(cfg0["max"])
        if any(e["negative"] or e["draw"] == "bars" for e in entries) or (any(e["fill"] for e in entries) and low > 0 and low < high * 0.2):
            low, high = min(low, 0), max(high, 0)
        ticks = _nice_ticks(low, high, max(2, min(6, int(plot_h // 22))))
        low, high = min(ticks[0], low), max(ticks[-1], high)
        unit0 = entries[0]["unit"]
        any_negative = any(e["negative"] for e in entries)
        labels = [format_value(abs(t) if any_negative else t, unit0, cfg0.get("decimals")) for t in ticks]
        label_w = max(self.width(l, 6.5) for l in labels) + 5
        px, pw = x + label_w, w - label_w - 4
        c = self.c

        def sx(t):
            return px + (t - start_ms) / (end_ms - start_ms or 1) * pw

        def sy(v):
            return plot_bottom + (v - low) / (high - low or 1) * plot_h

        c.setLineWidth(0.4)
        c.setStrokeColor(_rgb(GRID))
        for tick, label in zip(ticks, labels):
            yy = sy(tick)
            c.line(px, yy, px + pw, yy)
            self.text(px - 3, yy - 2.2, label, 6.5, MUTED, align="right")
        span_s = (end_ms - start_ms) / 1000
        step = next((s for s in TIME_STEPS if span_s / s <= max(3, pw / 70)), TIME_STEPS[-1])
        pattern = "%d.%m" if step >= 86400 else "%d.%m %H:%M" if span_s > 86400 else "%H:%M"
        first = math.ceil(start_ms / 1000 / step) * step
        t = first
        while t * 1000 <= end_ms:
            xx = sx(t * 1000)
            c.setStrokeColor(_rgb(GRID))
            c.line(xx, plot_bottom, xx, plot_bottom + plot_h)
            self.text(xx, plot_bottom - 8, datetime.fromtimestamp(t, timezone.utc).astimezone(self.tz).strftime(pattern), 6.2, MUTED, align="center")
            t += step
        steps = ((cfg0.get("thresholds") or {}).get("steps")) or []
        style = ((cfg0.get("custom") or {}).get("thresholdsStyle") or {}).get("mode", "off")
        if style in ("line", "line+area", "area"):
            for th in steps:
                if th.get("value") is None or not low <= float(th["value"]) <= high:
                    continue
                c.setStrokeColor(_rgb(th.get("color"), 0.9))
                c.setDash(3, 2)
                c.line(px, sy(float(th["value"])), px + pw, sy(float(th["value"])))
                c.setDash()
        zero = sy(0) if low <= 0 <= high else plot_bottom
        for e in entries:
            pts = e["points"]
            if len(pts) > pw * 2:
                pts = self._downsample(pts, int(pw))
            stroke = _rgb(e["color"])
            if e["draw"] == "bars":
                bar_w = max(0.6, min(6, pw / max(1, len(pts)) * 0.7))
                c.setFillColor(_rgb(e["color"], max(0.3, (e["fill"] or 80) / 100)))
                for ts, v in pts:
                    if v is None:
                        continue
                    xx = sx(ts)
                    c.rect(xx - bar_w / 2, min(zero, sy(v)), bar_w, max(0.3, abs(sy(v) - zero)), stroke=0, fill=1)
                continue
            segments, current = [], []
            for ts, v in pts:
                if v is None:
                    if not e["span"] and current:
                        segments.append(current)
                        current = []
                    continue
                current.append((sx(ts), sy(v)))
            if current:
                segments.append(current)
            for seg in segments:
                if e["step"] and len(seg) > 1:
                    stepped = [seg[0]]
                    for previous, point in zip(seg, seg[1:]):
                        stepped.extend([(point[0], previous[1]), point])
                    seg = stepped
                if e["fill"] and len(seg) > 1:
                    path = c.beginPath()
                    path.moveTo(seg[0][0], zero)
                    for xx, yy in seg:
                        path.lineTo(xx, yy)
                    path.lineTo(seg[-1][0], zero)
                    path.close()
                    c.setFillColor(_rgb(e["color"], min(0.6, e["fill"] / 100)))
                    c.drawPath(path, stroke=0, fill=1)
                c.setStrokeColor(stroke)
                c.setLineWidth(max(0.4, float(e["width"] or 1) * 0.7))
                if len(seg) == 1 or e["draw"] == "points":
                    c.setFillColor(stroke)
                    for xx, yy in seg:
                        c.circle(xx, yy, 0.9, stroke=0, fill=1)
                    continue
                path = c.beginPath()
                path.moveTo(*seg[0])
                for point in seg[1:]:
                    path.lineTo(*point)
                if e.get("previous"):
                    c.setDash(3, 2)
                c.drawPath(path, stroke=1, fill=0)
                c.setDash()
        c.setStrokeColor(_rgb("#c9ced8"))
        c.setLineWidth(0.6)
        c.line(px, plot_bottom, px + pw, plot_bottom)
        if legend_h:
            self._legend(entries, calcs, legend_mode, x, y, w, legend_h)

    def _downsample(self, points, buckets):
        size = max(1, math.ceil(len(points) / max(1, buckets)))
        out = []
        for i in range(0, len(points), size):
            chunk = [p for p in points[i : i + size] if p[1] is not None]
            if not chunk:
                out.append(points[i])
                continue
            lo = min(chunk, key=lambda p: p[1])
            hi = max(chunk, key=lambda p: p[1])
            out.extend(sorted({lo, hi}, key=lambda p: p[0]))
        return out

    def _legend(self, entries, calcs, mode, x, y, w, h):
        rows_fit = max(1, int((h - 2) // 9.5))
        line_y = y + h - 8
        if mode == "table" or calcs:
            col_w = 58
            name_w = w - col_w * len(calcs) - 14
            if calcs:
                for i, calc in enumerate(calcs):
                    self.text(
                        x + 14 + name_w + col_w * (i + 1),
                        line_y,
                        SHORT_CALCS.get(calc, REDUCERS.get(calc, calc)),
                        6.5,
                        "#1f60c4",
                        bold=True,
                        align="right",
                        max_width=col_w - 4,
                    )
                line_y -= 9.5
                rows_fit -= 1
            shown = entries[:rows_fit] if len(entries) <= rows_fit else entries[: rows_fit - 1]
            for e in shown:
                self.c.setFillColor(_rgb(e["color"]))
                self.c.rect(x + 2, line_y + 1, 8, 3, stroke=0, fill=1)
                self.text(x + 13, line_y, e["name"], 6.8, INK, max_width=name_w)
                for i, calc in enumerate(calcs):
                    value = reduce_values(e["values"], calc)
                    self.text(x + 14 + name_w + col_w * (i + 1), line_y, format_value(value, e["unit"], e["cfg"].get("decimals")), 6.8, INK, align="right")
                line_y -= 9.5
            if len(shown) < len(entries):
                self.text(x + 13, line_y, f"+{len(entries) - len(shown)} seri daha (Excel/CSV’de tam liste)", 6.5, FAINT)
            return
        cursor_x = x + 2
        rows_used = 1
        for index, e in enumerate(entries):
            label_w = min(self.width(e["name"], 6.8) + 18, w * 0.45)
            if cursor_x + label_w > x + w:
                rows_used += 1
                if rows_used > rows_fit:
                    self.text(cursor_x, line_y, f"+{len(entries) - index}", 6.5, FAINT)
                    return
                cursor_x = x + 2
                line_y -= 9.5
            self.c.setFillColor(_rgb(e["color"]))
            self.c.rect(cursor_x, line_y + 1, 8, 3, stroke=0, fill=1)
            self.text(cursor_x + 11, line_y, e["name"], 6.8, INK, max_width=label_w - 14)
            cursor_x += label_w + 4

    # single values ------------------------------------------------------------
