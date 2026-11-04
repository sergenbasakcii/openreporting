"""Server-side vector PDF renderer for dashboard reports (ReportLab, no browser).

Draws every visualization type the dashboard supports, lays panels out on the
same 24-column grid (or a simple one-panel-per-row flow), paginates long
tables, and adds a cover page with variables, time range and table of contents.
"""

import io
import math
from .. import smart_layout
from .layout_pdf import draw as draw_layout
from datetime import datetime, timezone
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from ..timerange import zone
from .collect import variable_summary
from .pdf_base import (
    PAPERS,
    FONT,
    BOLD,
    INK,
    MUTED,
    FAINT,
    GRID,
    PANEL_BG,
    BRAND,
    BRAND_2,
    NIGHT,
    TINT,
    MARGIN,
    HEADER_H,
    FOOTER_H,
    _fonts,
    _rgb,
    _gradient,
    _fit,
)
from .pdf_series import SeriesMixin
from .pdf_tables import TablesMixin
from .pdf_values import ValuesMixin


class Pdf(SeriesMixin, ValuesMixin, TablesMixin):
    def __init__(self, config, collected, title, *, generated_at=None, logo=None, images=None):
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
        self.images = images or {}

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

    def watermark(self):
        text = str(self.config.get("watermark") or "").strip()[:40]
        if not text:
            return
        c = self.c
        c.saveState()
        c.translate(self.page_w / 2, self.page_h / 2)
        c.rotate(35)
        size = min(96, self.page_w * 1.1 / max(4, len(text)))
        c.setFont(BOLD, size)
        c.setFillColor(_rgb("#94a3b8", 0.16))
        c.drawCentredString(0, -size / 3, text)
        c.restoreState()

    def new_page(self):
        if self.page:
            self.watermark()  # on top of the finished page, so panel backgrounds cannot hide it
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
            period = getattr(result, "period", None)
            label = ""
            if period:
                fmt = "%d.%m.%Y" if period[1] - period[0] >= 2 * 86400000 else "%d.%m.%Y %H:%M"
                label = f"{self._fmt_time(datetime.fromtimestamp(period[0] / 1000, timezone.utc), fmt)} – {self._fmt_time(datetime.fromtimestamp(period[1] / 1000, timezone.utc), fmt)}"
                self.text(x + w - 8, y + h - 12, label, 6.5, MUTED, align="right", max_width=w * 0.45)
            self.text(x + 13, y + h - 12, title, 8.5, INK, bold=True, max_width=w - 32 - (self.width(label, 6.5) + 8 if label else 0))
        if result.errors or result.warnings:
            mark = "!" if result.errors else "i"
            fill = "#d10e5c" if result.errors else "#f5b73d"
            c.setFillColor(_rgb(fill))
            c.circle(x + w - 10, y + h - 9, 4, stroke=0, fill=1)
            self.text(x + w - 10, y + h - 11.5, mark, 6, "#ffffff", bold=True, align="center")
        caption = str((result.panel.get("options") or {}).get("caption") or "").strip()
        if caption and h > 60:
            # Caption under the chart: up to two wrapped lines, the chart area shrinks accordingly.
            lines = self.wrap(caption, 7.5, w - 16)[:2]
            for i, line in enumerate(lines):
                self.text(x + 8, y + 6 + (len(lines) - 1 - i) * 9.5, line, 7.5, MUTED, max_width=w - 16)
            pad = 6 + len(lines) * 9.5
            return x + 6, y + pad + 2, w - 12, h - (20 if title else 8) - pad
        return x + 6, y + 5, w - 12, h - (20 if title else 8)

    def draw_panel(self, result, x, y, w, h):
        kind = result.panel.get("type", "timeseries")
        if draw_layout(self, result, x, y, w, h):
            return
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
        if kind == "narrative":
            self.draw_narrative(result.panel, frames, bx, by, bw, bh)
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
        # Smart dashboards: every section (e.g. one per host) starts on fresh pages; its name goes in the page header.
        smart = smart_layout.is_smart(pdf.collected.dashboard)
        header_h = 18 if section.title and not smart else 0
        if config.get("layout", "grid") == "grid":
            placements, page_count = plan_grid(pdf, section)
            first_h = max((top + ph for pi, _, _, top, _, ph in placements if pi == 0), default=20)
            if state["cursor"] is None or smart or config.get("section_page_break") or page_count > 1 or state["cursor"] + header_h + first_h > usable:
                if not (state["cursor"] == 0 and pages and not pages[-1]["ops"]):
                    new_page(section.title)
            toc.append((section.title, first_page + len(pages) - 1))
            if section.title and not smart:
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


def render_pdf(config, collected, title, logo=None, images=None):
    if smart_layout.is_smart(collected.dashboard):
        config = {**config, **smart_layout.report_overrides(collected.dashboard)}
    pdf = Pdf(config, collected, title, logo=logo, images=images)
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
    pdf.watermark()
    pdf.c.save()
    return pdf.buffer.getvalue()
