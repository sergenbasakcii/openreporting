"""Shared PDF palette, fonts, paper sizes and drawing helpers (split from pdf.py)."""

import math
from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A3, A4, LETTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from ..portable import unicode_bold_font_path, unicode_font_path
from .fieldcfg import color as named_color

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
