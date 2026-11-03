"""Server-side vector PDF renderer for dashboard reports (ReportLab, no browser).

Draws every visualization type the dashboard supports, lays panels out on the
same 24-column grid (or a simple one-panel-per-row flow), paginates long
tables, and adds a cover page with variables, time range and table of contents.
"""

import io
import math
from .. import smart_layout
from datetime import datetime, timezone

from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A3, A4, LETTER, landscape, portrait
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from ..frames import REDUCERS, reduce_values
from ..portable import unicode_bold_font_path, unicode_font_path
from ..timerange import zone
from ..units import format_value, resolve_unit
from .collect import variable_summary
from .fieldcfg import contrast, display_name, field_config, fmt, mapped, options, reduced_items, series_color, threshold_color, color as named_color

PAPERS = {"A4": A4, "A3": A3, "Letter": LETTER}
FONT, BOLD = "OpenReporting-Sans", "OpenReporting-Sans-Bold"
# OpenReporting print palette (Porcelain theme): ink text, teal signal colour, indigo secondary.
INK, MUTED, FAINT, GRID, PANEL_BG, BRAND = "#141a2a", "#566074", "#8a93a3", "#e3e6ec", "#ffffff", "#0d9488"
BRAND_2, NIGHT, TINT, BRAND_INK = "#4f46e5", "#0b1020", "#eaf6f4", "#0f766e"
SHORT_CALCS = {
    "mean": "Ort.",
    "max": "Maks.",
    "min": "Min.",
    "lastNotNull": "Son",
    "last": "Son",
    "sum": "Toplam",
    "count": "Sayı",
    "firstNotNull": "İlk",
    "first": "İlk",
    "range": "Aralık",
    "delta": "Delta",
    "diff": "Fark",
    "median": "Medyan",
    "p90": "p90",
    "p95": "p95",
    "p99": "p99",
    "stdDev": "Std.",
    "nullCount": "Boş",
}
TIME_STEPS = [60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 172800, 604800, 1209600, 2592000]
MARGIN, HEADER_H, FOOTER_H = 26, 30, 16
STAT_MIN_W, STAT_MIN_H = 64, 34


def _fonts():
    names = pdfmetrics.getRegisteredFontNames()
    if FONT not in names:
        pdfmetrics.registerFont(TTFont(FONT, unicode_font_path()))
    if BOLD not in names:
        pdfmetrics.registerFont(TTFont(BOLD, unicode_bold_font_path()))


def _rgb(value, alpha=1.0):
    hexv = named_color(value).lstrip("#")
    r, g, b = (int(hexv[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return Color(r, g, b, alpha=alpha)


def _nice_ticks(low, high, count=5):
    if low == high:
        low, high = low - 1, high + 1
    span = high - low
    raw = span / max(1, count)
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=10 * mag)
    start = math.floor(low / step) * step
    end = math.ceil(high / step) * step
    ticks = []
    value = start
    while value <= end + step * 1e-9 and len(ticks) < 50:
        ticks.append(round(value, 12))
        value += step
    return ticks


def _gradient(c, x, y, w, h, start=BRAND, end=BRAND_2, steps=48):
    """Horizontal brand gradient made of thin slices (PDF viewers render it identically)."""
    a, b = _rgb(start), _rgb(end)
    step = w / steps
    for i in range(steps):
        t = i / (steps - 1) if steps > 1 else 0.0
        c.setFillColor(Color(a.red + (b.red - a.red) * t, a.green + (b.green - a.green) * t, a.blue + (b.blue - a.blue) * t))
        c.rect(x + i * step, y, step + 0.4, h, stroke=0, fill=1)


def _fit(width, height, box_w, box_h):
    """Largest size of a width×height image inside box_w×box_h, keeping its aspect ratio."""
    scale = min(box_w / width, box_h / height)
    return width * scale, height * scale


class Pdf:
    def __init__(self, config, collected, title, *, generated_at=None, logo=None):
        _fonts()
        size = PAPERS.get(config.get("paper", "A4"), A4)
        self.page_w, self.page_h = landscape(size) if config.get("orientation", "landscape") == "landscape" else portrait(size)
        self.config = config
        self.collected = collected
        self.title = title
        self.tz = zone(collected.timezone)
        self.generated = generated_at or datetime.now(timezone.utc)
        self.buffer = io.BytesIO()
        self.c = canvas.Canvas(self.buffer, pagesize=(self.page_w, self.page_h), pageCompression=1)
        self.c.setTitle(title)
        self.c.setAuthor("OpenReporting")
        self.c.setCreator("OpenReporting")
        # Customer logo (validated PNG bytes); ImageReader is shared so the image is embedded once.
        self.logo = ImageReader(io.BytesIO(logo)) if logo else None
        self.c.setSubject(f"{self._fmt_time(collected.start)} – {self._fmt_time(collected.end)}")
        self.page = 0
        self.section_title = ""
        self.content_w = self.page_w - 2 * MARGIN
        self.top = self.page_h - MARGIN - HEADER_H
        self.bottom = MARGIN + FOOTER_H
        self.toc = []

    # -- primitives -------------------------------------------------------
    def _fmt_time(self, dt, pattern="%d.%m.%Y %H:%M"):
        return dt.astimezone(self.tz).strftime(pattern)

    def text(self, x, y, value, size=8, color=INK, bold=False, max_width=None, align="left"):
        font = BOLD if bold else FONT
        value = str(value if value is not None else "").replace("\r", " ").replace("\n", " ")
        if max_width is not None and max_width > 4:
            while value and pdfmetrics.stringWidth(value, font, size) > max_width:
                value = value[:-2] + "…" if len(value) > 2 else ""
        self.c.setFont(font, size)
        self.c.setFillColor(_rgb(color))
        if align == "right":
            self.c.drawRightString(x, y, value)
        elif align == "center":
            self.c.drawCentredString(x, y, value)
        else:
            self.c.drawString(x, y, value)

    def width(self, value, size=8, bold=False):
        return pdfmetrics.stringWidth(str(value), BOLD if bold else FONT, size)

    def wrap(self, value, size, max_width, bold=False):
        words, lines, line = str(value).split(), [], ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if self.width(candidate, size, bold) <= max_width or not line:
                line = candidate
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)
        return lines

    def new_page(self):
        if self.page:
            self.c.showPage()
        self.page += 1
        c = self.c
        _gradient(c, 0, self.page_h - 4, self.page_w, 4)
        # Brand mark: rounded tile with the initial, then the report title.
        mark_y = self.page_h - MARGIN - 17
        _gradient(c, MARGIN, mark_y, 16, 16)
        c.setFillColor(_rgb("#ffffff"))
        c.setStrokeColor(_rgb("#ffffff"))
        c.setLineWidth(2.2)
        c.roundRect(MARGIN - 1.1, mark_y - 1.1, 18.2, 18.2, 5, stroke=1, fill=0)
        self.text(MARGIN + 8, mark_y + 4.2, "O", 9, "#ffffff", bold=True, align="center")
        self.text(MARGIN + 22, self.page_h - MARGIN - 12, self.title, 11, INK, bold=True, max_width=self.content_w * 0.55)
        if self.section_title:
            self.text(MARGIN + 22, self.page_h - MARGIN - 24, self.section_title, 8.5, MUTED, max_width=self.content_w * 0.55)
        right = self.page_w - MARGIN
        if self.logo and self.config.get("logo_on_pages", True):
            # Header logo: right-aligned in the header band, at most 22pt high / 96pt wide.
            lw, lh = _fit(*self.logo.getSize(), 96, HEADER_H - 8)
            c.drawImage(self.logo, right - lw, self.top + 6 + (HEADER_H - 8 - lh) / 2, lw, lh, mask="auto")
            right -= lw + 12
        self.text(right, self.page_h - MARGIN - 12, f"{self._fmt_time(self.collected.start)} – {self._fmt_time(self.collected.end)}", 8.5, MUTED, align="right")
        self.text(right, self.page_h - MARGIN - 24, self.collected.timezone, 7.5, FAINT, align="right")
        c.setStrokeColor(_rgb(GRID))
        c.setLineWidth(0.6)
        c.line(MARGIN, self.top + 2, self.page_w - MARGIN, self.top + 2)
        footer = self.config.get("footer_text") or "OpenReporting raporu"
        self.text(MARGIN, MARGIN, f"{footer} · oluşturulma {self._fmt_time(self.generated, '%d.%m.%Y %H:%M')}", 7, FAINT, max_width=self.content_w * 0.7)
        self.text(self.page_w - MARGIN, MARGIN, f"Sayfa {self.page}", 7, FAINT, align="right")

    # -- cover ----------------------------------------------------------------
    def cover(self, toc_pages):
        self.page += 1
        c = self.c
        c.setFillColor(_rgb(NIGHT))
        c.rect(0, self.page_h - 150, self.page_w, 150, stroke=0, fill=1)
        # Soft glow circles in the band (brand colours at low alpha) and the brand stripe below it.
        c.setFillColor(_rgb(BRAND, 0.18))
        c.circle(self.page_w * 0.18, self.page_h - 10, 120, stroke=0, fill=1)
        c.setFillColor(_rgb(BRAND_2, 0.2))
        c.circle(self.page_w * 0.9, self.page_h - 30, 110, stroke=0, fill=1)
        _gradient(c, 0, self.page_h - 154, self.page_w, 4)
        text_w = self.content_w - 10
        if self.logo and self.config.get("logo_on_cover", True):
            # Cover logo: white card on the right of the dark band, so dark and transparent logos stay visible.
            pad, box_w, box_h = 12, 170, 86
            lw, lh = _fit(*self.logo.getSize(), box_w, box_h)
            card_w, card_h = lw + 2 * pad, lh + 2 * pad
            card_x = self.page_w - MARGIN - card_w
            card_y = self.page_h - 75 - card_h / 2
            c.setFillColor(_rgb("#ffffff"))
            c.roundRect(card_x, card_y, card_w, card_h, 6, stroke=0, fill=1)
            c.drawImage(self.logo, card_x + pad, card_y + pad, lw, lh, mask="auto")
            text_w = card_x - MARGIN - 24
        self.text(MARGIN + 4, self.page_h - 50, "OPENREPORTING · RAPOR", 9, "#2dd4bf", bold=True)
        lines = self.wrap(self.title, 22, text_w, bold=True)[:2]
        for i, line in enumerate(lines):
            self.text(MARGIN + 4, self.page_h - 82 - i * 26, line, 22, "#ffffff", bold=True)
        dash_title = self.collected.dashboard.get("title", "")
        self.text(MARGIN + 4, self.page_h - 136, f"Dashboard: {dash_title}", 9.5, "#c7cbd6", max_width=text_w)
        y = self.page_h - 190
        rows = [
            ("Rapor dönemi", f"{self._fmt_time(self.collected.start)} – {self._fmt_time(self.collected.end)}"),
            ("Saat dilimi", self.collected.timezone),
            ("Oluşturulma", self._fmt_time(self.generated, "%d.%m.%Y %H:%M:%S")),
            ("Bölüm sayısı", str(len(self.collected.sections))),
        ]
        if self.config.get("split_by"):
            rows.append(("Bölümleme", f"${self.config['split_by']} değişkeninin her değeri için ayrı bölüm"))
        rows += [(str(name), value) for name, value in variable_summary(self.collected.variables)]
        # Metadata block on a tinted card with a brand accent edge.
        card_h = 14 + sum(min(3, len(self.wrap(v, 9, self.content_w - 160)) or 1) * 11 + 6 for _, v in rows)
        c.setFillColor(_rgb(TINT))
        c.roundRect(MARGIN, y - card_h + 14, self.content_w, card_h, 8, stroke=0, fill=1)
        c.setFillColor(_rgb(BRAND))
        c.rect(MARGIN, y - card_h + 22, 3, card_h - 16, stroke=0, fill=1)
        y -= 4
        for key, value in rows:
            self.text(MARGIN + 14, y, key, 9, MUTED)
            for i, line in enumerate(self.wrap(value, 9, self.content_w - 160)[:3]):
                self.text(MARGIN + 150, y - i * 11, line, 9, INK, bold=i == 0 and key == "Rapor dönemi")
            y -= 15 + 11 * max(0, min(2, len(self.wrap(value, 9, self.content_w - 160)) - 1))
        if self.collected.partial:
            y -= 6
            c.setFillColor(_rgb("#fff4e5"))
            c.setStrokeColor(_rgb("#f5b73d"))
            c.roundRect(MARGIN, y - 30, self.content_w, 34, 4, stroke=1, fill=1)
            self.text(MARGIN + 10, y - 10, "Kısmi veri uyarısı", 9, "#8a5a00", bold=True)
            issues = self.collected.warnings + [
                f"{p.title or p.panel.get('type')}: {(p.errors or p.warnings)[0]}" for s in self.collected.sections for p in s.panels if p.errors or p.warnings
            ]
            self.text(
                MARGIN + 10,
                y - 22,
                f"{len(issues)} panelde hata/eksik veri var. İlk: {issues[0] if issues else ''}",
                8,
                "#8a5a00",
                max_width=self.content_w - 20,
            )
            y -= 44
        if toc_pages and len(self.collected.sections) > 1:
            y -= 8
            self.text(MARGIN + 4, y, "İçindekiler", 11, INK, bold=True)
            y -= 16
            columns = 2 if len(toc_pages) > 12 else 1
            col_w = (self.content_w - 8) / columns
            per_col = max(1, math.ceil(len(toc_pages) / columns))
            for index, (title, page) in enumerate(toc_pages):
                col, row = divmod(index, per_col)
                yy = y - row * 12
                if yy < self.bottom + 10:
                    continue
                xx = MARGIN + 4 + col * col_w
                self.text(xx, yy, title, 8.5, INK, max_width=col_w - 50)
                self.text(xx + col_w - 12, yy, str(page), 8.5, MUTED, align="right")
        self.text(MARGIN, MARGIN, "Bu rapor salt-okunur kaynaklardan otomatik üretilmiştir. Veri olmayan noktalar sıfır kabul edilmez.", 7, FAINT)
        self.text(self.page_w - MARGIN, MARGIN, f"Sayfa {self.page}", 7, FAINT, align="right")

    # -- panels -----------------------------------------------------------------
    def panel_frame(self, x, y, w, h, result):
        c = self.c
        transparent = result.panel.get("transparent")
        if not transparent:
            c.setFillColor(_rgb(PANEL_BG))
            c.setStrokeColor(_rgb(GRID))
            c.setLineWidth(0.6)
            c.roundRect(x, y, w, h, 6, stroke=1, fill=1)
        title = result.title
        if title:
            c.setFillColor(_rgb(BRAND))
            c.roundRect(x + 7, y + h - 12.5, 2.4, 8, 1.2, stroke=0, fill=1)
            self.text(x + 13, y + h - 12, title, 8.5, INK, bold=True, max_width=w - 32)
        if result.errors or result.warnings:
            mark = "!" if result.errors else "i"
            fill = "#d10e5c" if result.errors else "#f5b73d"
            c.setFillColor(_rgb(fill))
            c.circle(x + w - 10, y + h - 9, 4, stroke=0, fill=1)
            self.text(x + w - 10, y + h - 11.5, mark, 6, "#ffffff", bold=True, align="center")
        return x + 6, y + 5, w - 12, h - (20 if title else 8)

    def draw_panel(self, result, x, y, w, h):
        kind = result.panel.get("type", "timeseries")
        if kind == "row":
            self.text(x + 2, y + h - 11, result.title or "Satır", 10.5, INK, bold=True, max_width=w)
            self.c.setStrokeColor(_rgb(BRAND))
            self.c.setLineWidth(1)
            self.c.line(x, y + h - 15, x + min(w, self.width(result.title or "Satır", 10.5, True) + 10), y + h - 15)
            return
        bx, by, bw, bh = self.panel_frame(x, y, w, h, result)
        if bw < 20 or bh < 12:
            return
        frames = result.frames
        if result.errors and not frames:
            for i, line in enumerate(self.wrap("; ".join(result.errors), 7.5, bw - 10)[: max(1, int(bh // 10))]):
                self.text(bx + bw / 2, by + bh / 2 + 6 - i * 10, line, 7.5, "#c4162a", align="center")
            return
        if kind == "text":
            self.draw_text(result.panel, bx, by, bw, bh)
            return
        if not frames or all((f["type"] == "timeseries" and not f["points"]) or (f["type"] == "table" and not f["rows"]) for f in frames):
            self.text(bx + bw / 2, by + bh / 2 - 3, "Veri yok", 10, FAINT, align="center")
            return
        has_series = any(f["type"] == "timeseries" for f in frames)
        try:
            from .extended_pdf import draw as draw_extended

            if draw_extended(self, result.panel, frames, bx, by, bw, bh):
                return
            from .categorical_pdf import draw as draw_categorical

            if draw_categorical(self, result.panel, frames, bx, by, bw, bh):
                return
            if kind in ("timeseries",) and has_series:
                self.draw_timeseries(result.panel, frames, bx, by, bw, bh)
            elif kind == "statetimeline" and has_series:
                self.draw_state_timeline(result.panel, frames, bx, by, bw, bh)
            elif kind == "stat":
                self.draw_stat(result.panel, frames, bx, by, bw, bh)
            elif kind == "gauge":
                self.draw_gauge(result.panel, frames, bx, by, bw, bh)
            elif kind in ("bargauge", "barchart"):
                self.draw_bars(result.panel, frames, bx, by, bw, bh, kind)
            elif kind == "piechart":
                self.draw_pie(result.panel, frames, bx, by, bw, bh)
            elif kind == "donut":
                self.draw_pie({**result.panel, "options": {**result.panel.get("options", {}), "pieType": "donut"}}, frames, bx, by, bw, bh)
            elif kind in ("stepchart", "stackedarea") and has_series:
                cfg = result.panel.get("fieldConfig", {})
                defaults = cfg.get("defaults", {})
                custom = {**defaults.get("custom", {})}
                if kind == "stepchart":
                    custom["lineInterpolation"] = "stepAfter"
                else:
                    custom.update(stacking={"mode": "normal"}, fillOpacity=40)
                self.draw_timeseries({**result.panel, "fieldConfig": {**cfg, "defaults": {**defaults, "custom": custom}}}, frames, bx, by, bw, bh)
            elif kind == "statusgrid":
                self.draw_statusgrid(result.panel, frames, bx, by, bw, bh)
            else:
                from ..dashboards import EXTRA_PANEL_TYPES

                if kind in EXTRA_PANEL_TYPES or kind.startswith("x-"):
                    self.text(bx, by + bh - 8, "Grafik verisi · tablo görünümü", 7, MUTED)
                    bh -= 16
                self.draw_table(result.panel, frames, bx, by, bw, bh)
        except Exception as exc:  # noqa: BLE001 - one bad panel must not break the document
            self.text(bx + bw / 2, by + bh / 2, f"Çizim hatası: {type(exc).__name__}", 8, "#c4162a", align="center")

    # time series -----------------------------------------------------------
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
                }
            )
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
                c.drawPath(path, stroke=1, fill=0)
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
    def _grid(self, count, w, h):
        cols = max(1, min(count, round(math.sqrt(count * (w / max(1, h))))))
        rows = math.ceil(count / cols)
        return cols, rows

    def draw_stat(self, panel, frames, x, y, w, h):
        items = reduced_items(panel, frames)
        if not items:
            self.text(x + w / 2, y + h / 2, "Veri yok", 10, FAINT, align="center")
            return
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
    def table_model(self, panel, frames):
        tables = [f for f in frames if f["type"] == "table"]
        if tables:
            table = tables[0]
        else:
            series = [f for f in frames if f["type"] == "timeseries"]
            stamps = sorted({p[0] for f in series for p in f["points"]}, reverse=True)
            lookups = [dict(f["points"]) for f in series]
            table = {
                "columns": [{"name": "Zaman", "type": "time"}] + [{"name": display_name(f), "type": "number", "unit": f.get("unit", "")} for f in series],
                "rows": [[t] + [lk.get(t) for lk in lookups] for t in stamps],
                "meta": {},
            }
        cfgs = [field_config(panel, table, c["name"]) for c in table["columns"]]
        visible = [i for i, cfg in enumerate(cfgs) if not (cfg.get("custom") or {}).get("hidden")]
        row_units = (table.get("meta") or {}).get("rowUnits") or []
        rendered = []
        for ri, row in enumerate(table["rows"]):
            cells = []
            for ci in visible:
                column, cfg, value = table["columns"][ci], cfgs[ci], row[ci]
                if column["type"] == "time":
                    text = "—" if value is None else datetime.fromtimestamp(value / 1000, timezone.utc).astimezone(self.tz).strftime("%d.%m.%Y %H:%M")
                    cells.append((text, None, "left"))
                elif column["type"] == "number":
                    unit = resolve_unit(cfg.get("unit"), column.get("unit") or (row_units[ri] if ri < len(row_units) else ""))
                    cell_mode = ((cfg.get("custom") or {}).get("cellOptions") or {}).get("type", "auto")
                    colr = (
                        threshold_color(value, cfg.get("thresholds"), cfg.get("min") or 0, cfg.get("max") or 100)
                        if cell_mode in ("color-text", "color-background", "gauge") and value is not None
                        else None
                    )
                    hit = mapped(value, cfg.get("mappings"))
                    if hit and hit.get("color"):
                        colr = named_color(hit["color"])
                    cells.append((fmt(value, cfg, unit) if value is not None else (cfg.get("noValue") or "—"), (colr, cell_mode), "right"))
                else:
                    hit = mapped(value, cfg.get("mappings"))
                    cells.append(
                        (
                            hit.get("text") if hit and hit.get("text") else ("" if value is None else str(value)),
                            (named_color(hit["color"]), "color-text") if hit and hit.get("color") else None,
                            "left",
                        )
                    )
            rendered.append(cells)
        headers = [cfgs[i].get("displayName") or table["columns"][i]["name"] for i in visible]
        return headers, rendered

    def column_widths(self, headers, rows, width):
        natural = []
        for i, head in enumerate(headers):
            sample = [self.width(r[i][0], 7) for r in rows[:200]]
            natural.append(min(220, max([self.width(head, 7, True)] + sample) + 10))
        total = sum(natural) or 1
        if total <= width:
            extra = (width - total) / len(natural)
            return [n + extra for n in natural]
        return [n * width / total for n in natural]

    def draw_table(self, panel, frames, x, y, w, h, rows_override=None, start_row=0, continued=False):
        headers, rows = self.table_model(panel, frames) if rows_override is None else rows_override
        if not headers:
            return 0
        widths = self.column_widths(headers, rows, w)
        row_h = 11
        line_y = y + h - row_h
        self.c.setFillColor(_rgb(TINT))
        self.c.roundRect(x, line_y - 2, w, row_h, 2, stroke=0, fill=1)
        cx = x
        for head, width in zip(headers, widths):
            self.text(cx + 3, line_y + 1.5, head, 7, BRAND_INK, bold=True, max_width=width - 6)
            cx += width
        capacity = max(0, int((h - row_h - 10) // row_h))
        chunk = rows[start_row : start_row + capacity]
        for index, cells in enumerate(chunk):
            line_y -= row_h
            if index % 2:
                self.c.setFillColor(_rgb("#f7f9fb"))
                self.c.rect(x, line_y - 2, w, row_h, stroke=0, fill=1)
            cx = x
            for (text, style, align), width in zip(cells, widths):
                colr = INK
                if style and style[0]:
                    if style[1] in ("color-background", "color-background-solid"):
                        self.c.setFillColor(_rgb(style[0], 0.85))
                        self.c.rect(cx + 0.5, line_y - 1.5, width - 1, row_h - 1, stroke=0, fill=1)
                        colr = contrast(style[0])
                    elif style[1] == "gauge":
                        self.c.setFillColor(_rgb(style[0]))
                        self.c.rect(cx + 2, line_y + 0.5, (width - 4) * 0.35, 4, stroke=0, fill=1)
                    else:
                        colr = style[0]
                if align == "right":
                    self.text(cx + width - 3, line_y + 1.5, text, 7, colr, align="right", max_width=width - 6)
                else:
                    self.text(cx + 3, line_y + 1.5, text, 7, colr, max_width=width - 6)
                cx += width
        remaining = len(rows) - start_row - len(chunk)
        if remaining > 0 and rows_override is None:
            self.text(x + w, y + 1, f"… {remaining} satır daha (tam liste Excel/CSV çıktısında)", 6.5, FAINT, align="right")
        return len(chunk)


def _grid_metrics(pdf):
    col_w = pdf.content_w / 24
    unit = max(12, min(24, col_w * 0.62))
    return col_w, unit


def plan_grid(pdf, section):
    """Assign each panel to (page offset, x, y_top, w, h) using dashboard gridPos."""
    dashboard = pdf.collected.dashboard
    if smart_layout.is_smart(dashboard) and all("smartPos" in r.panel for r in section.panels):
        # Smart dashboards print exactly what the page canvas showed: fixed pages, 24 × rows cells.
        return smart_layout.plan(section.panels, dashboard["smart"]["rows"], pdf.content_w / smart_layout.COLUMNS, pdf.top - pdf.bottom)
    col_w, unit = _grid_metrics(pdf)
    usable = pdf.top - pdf.bottom - 20
    placements = []
    page_index = 0
    page_start = None
    for result in sorted(section.panels, key=lambda r: (r.panel["gridPos"]["y"], r.panel["gridPos"]["x"])):
        pos = result.panel["gridPos"]
        height = min(usable, (1.6 if result.panel.get("type") == "row" else pos["h"]) * unit)
        if page_start is None:
            page_start = pos["y"]
        top = (pos["y"] - page_start) * unit
        if top + height > usable + 0.5:
            page_index += 1
            page_start = pos["y"]
            top = 0
        placements.append((page_index, result, pos["x"] * col_w, top, pos["w"] * col_w, height))
    return placements, page_index + 1


SIMPLE_HEIGHTS = {
    "timeseries": 200,
    "statetimeline": 150,
    "barchart": 190,
    "bargauge": 170,
    "piechart": 190,
    "gauge": 140,
    "stat": 95,
    "statusgrid": 150,
    "text": 90,
    "row": 24,
}


def paginate(pdf, config, sections):
    """First pass: drawing operations grouped by page plus TOC page numbers.

    Sections flow one after another; a section starts a new page only when it
    does not fit in the remaining space (or ``section_page_break`` is set).
    """
    first_page = 2 if config.get("cover", True) else 1
    usable = pdf.top - pdf.bottom
    pages = []
    toc = []
    state = {"cursor": None}

    def new_page(title):
        pages.append({"title": title, "ops": []})
        state["cursor"] = 0

    for section in sections:
        header_h = 18 if section.title else 0
        if config.get("layout", "grid") == "grid":
            placements, page_count = plan_grid(pdf, section)
            first_h = max((top + ph for pi, _, _, top, _, ph in placements if pi == 0), default=20)
            if state["cursor"] is None or config.get("section_page_break") or page_count > 1 or state["cursor"] + header_h + first_h > usable:
                if not (state["cursor"] == 0 and pages and not pages[-1]["ops"]):
                    new_page(section.title)
            toc.append((section.title, first_page + len(pages) - 1))
            if section.title:
                pages[-1]["ops"].append(("section", section.title, state["cursor"]))
                state["cursor"] += header_h
            base = state["cursor"]
            current = 0
            bottom = base
            for page_index, result, px, top, pw, ph in placements:
                while current < page_index:
                    new_page(section.title)
                    current += 1
                    base = 0
                    bottom = 0
                pages[-1]["ops"].append(("panel", result, px, base + top, pw, ph))
                bottom = max(bottom, base + top + ph)
            if not placements:
                pages[-1]["ops"].append(("note", "Bu bölümde panel yok.", base))
                bottom = base + 16
            state["cursor"] = bottom + 10
            continue
        if state["cursor"] is None or config.get("section_page_break") or state["cursor"] + header_h + 100 > usable:
            new_page(section.title)
        toc.append((section.title, first_page + len(pages) - 1))
        if section.title:
            pages[-1]["ops"].append(("section", section.title, state["cursor"]))
            state["cursor"] += header_h
        max_rows = int(config.get("table_max_rows") or 500)
        for result in section.panels:
            kind = result.panel.get("type", "timeseries")
            if kind == "table" and result.frames and not result.errors:
                headers, rows = pdf.table_model(result.panel, result.frames)
                rows = rows[:max_rows]
                start, first = 0, True
                while True:
                    available = usable - state["cursor"]
                    if available < 60:
                        new_page(section.title)
                        available = usable
                    remaining = len(rows) - start
                    capacity = max(1, int((available - 31) // 11))
                    shown = min(capacity, remaining)
                    need = 32 + shown * 11
                    pages[-1]["ops"].append(
                        ("table", result, (headers, rows), start, state["cursor"], need, result.title if first else f"{result.title} (devam)")
                    )
                    state["cursor"] += need + 8
                    start += shown
                    first = False
                    if start >= len(rows) or shown == 0:
                        break
                continue
            height = SIMPLE_HEIGHTS.get(kind, 180)
            if state["cursor"] + height > usable:
                new_page(section.title)
            pages[-1]["ops"].append(("panel", result, 0, state["cursor"], pdf.content_w, height))
            state["cursor"] += height + 8
    if not pages:
        new_page("")
        pages[-1]["ops"].append(("note", "Rapor için bölüm üretilmedi.", 0))
    return pages, toc


def render_pdf(config, collected, title, logo=None):
    if smart_layout.is_smart(collected.dashboard):
        config = {**config, **smart_layout.report_overrides(collected.dashboard)}
    pdf = Pdf(config, collected, title, logo=logo)
    pages, toc = paginate(pdf, config, collected.sections)
    if config.get("cover", True):
        pdf.cover([(t or title, page) for t, page in toc] if config.get("toc", True) else [])
    gap = 3
    for page in pages:
        pdf.section_title = page["title"] if config.get("split_by") else ""
        pdf.new_page()
        for op in page["ops"]:
            kind = op[0]
            if kind == "section":
                _, text, top = op
                y = pdf.top - top - 14
                pdf.c.setFillColor(_rgb(TINT))
                pdf.c.roundRect(MARGIN, y - 4, pdf.content_w, 16, 4, stroke=0, fill=1)
                _gradient(pdf.c, MARGIN, y - 4, 3, 16, BRAND, BRAND, steps=1)
                pdf.text(MARGIN + 9, y + 1, text, 9.5, INK, bold=True, max_width=pdf.content_w - 20)
            elif kind == "note":
                _, text, top = op
                pdf.text(MARGIN, pdf.top - top - 14, text, 9, MUTED)
            elif kind == "panel":
                _, result, px, top, pw, ph = op
                pdf.draw_panel(result, MARGIN + px + gap / 2, pdf.top - top - ph + gap / 2, pw - gap, ph - gap)
            elif kind == "table":
                _, result, model, start, top, need, ptitle = op
                frame_result = type(result)(panel=result.panel, title=ptitle, errors=result.errors, warnings=result.warnings)
                bx, by, bw, bh = pdf.panel_frame(MARGIN, pdf.top - top - need, pdf.content_w, need, frame_result)
                pdf.draw_table(result.panel, None, bx, by, bw, bh, rows_override=model, start_row=start)
    pdf.c.save()
    return pdf.buffer.getvalue()
