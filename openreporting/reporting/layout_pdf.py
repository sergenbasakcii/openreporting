"""PDF drawing for layout elements that carry no query: image / logo, divider and report information."""

import io

from reportlab.lib.utils import ImageReader

LAYOUT_TYPES = {"image", "divider", "reportinfo"}


def _fit(width, height, box_w, box_h):
    scale = min(box_w / max(1, width), box_h / max(1, height))
    return width * scale, height * scale


def draw(pdf, result, x, y, w, h):
    """Draw a layout element; returns False for other panel types."""
    kind = result.panel.get("type")
    if kind not in LAYOUT_TYPES:
        return False
    options = dict(result.panel.get("options") or {})
    if kind == "reportinfo" and "_variables" in result.panel:
        options["_variables"] = result.panel["_variables"]
    if kind == "image":
        _image(pdf, options, x, y, w, h)
    elif kind == "divider":
        _divider(pdf, options, result.title, x, y, w, h)
    else:
        _report_info(pdf, options, x, y, w, h)
    return True


def _image(pdf, options, x, y, w, h):
    from .pdf import FAINT, GRID, _rgb

    data = (pdf.images or {}).get(options.get("logo_id"))
    if not data and not options.get("logo_id") and pdf.logo is not None:
        # An image element left empty shows the report logo (the usual intent on a cover/header row).
        iw, ih = _fit(*pdf.logo.getSize(), w - 4, h - 4)
        pdf.c.drawImage(pdf.logo, x + (w - iw) / 2, y + (h - ih) / 2, iw, ih, mask="auto")
        return
    if not data:
        pdf.c.setStrokeColor(_rgb(GRID))
        pdf.c.setDash(3, 3)
        pdf.c.roundRect(x, y, w, h, 6, stroke=1, fill=0)
        pdf.c.setDash()
        pdf.text(x + w / 2, y + h / 2 - 3, "Görsel bulunamadı", 8, FAINT, align="center")
        return
    image = ImageReader(io.BytesIO(data))
    iw, ih = _fit(*image.getSize(), w - 4, h - 4)
    align = options.get("align", "center")
    ix = x + 2 if align == "left" else x + w - iw - 2 if align == "right" else x + (w - iw) / 2
    pdf.c.drawImage(image, ix, y + (h - ih) / 2, iw, ih, mask="auto")


def _divider(pdf, options, title, x, y, w, h):
    from .pdf import BRAND, GRID, INK, _gradient, _rgb

    mid = y + h / 2
    if title:
        pdf.text(x + 2, mid + 4, title, 10.5, INK, bold=True, max_width=w - 4)
        mid -= 6
    if options.get("style") == "brand":
        _gradient(pdf.c, x, mid - 1, w, 2)
    else:
        pdf.c.setStrokeColor(_rgb(GRID if options.get("style") == "subtle" else BRAND))
        pdf.c.setLineWidth(0.8)
        pdf.c.line(x, mid, x + w, mid)


def _report_info(pdf, options, x, y, w, h):
    from .pdf import BRAND, INK, MUTED, TINT, _rgb
    from .collect import variable_summary

    collected = pdf.collected
    rows = [
        ("Rapor dönemi", f"{pdf._fmt_time(collected.start)} – {pdf._fmt_time(collected.end)}"),
        ("Saat dilimi", collected.timezone),
        ("Oluşturulma", pdf._fmt_time(pdf.generated, "%d.%m.%Y %H:%M")),
    ]
    if options.get("showVariables", True):
        summary = options.get("_variables") if options.get("_variables") is not None else variable_summary(collected.variables)
        rows += [(str(name), str(value)) for name, value in summary]
    if options.get("note"):
        rows.append(("Not", str(options["note"])))
    pdf.c.setFillColor(_rgb(TINT))
    pdf.c.roundRect(x, y, w, h, 6, stroke=0, fill=1)
    pdf.c.setFillColor(_rgb(BRAND))
    pdf.c.rect(x, y + 6, 3, h - 12, stroke=0, fill=1)
    line_h = 12
    capacity = max(1, int((h - 10) // line_h))
    label_w = min(110, w * 0.38)
    for index, (key, value) in enumerate(rows[:capacity]):
        line_y = y + h - 14 - index * line_h
        pdf.text(x + 10, line_y, key, 8, MUTED, max_width=label_w - 6)
        pdf.text(x + 10 + label_w, line_y, value, 8, INK, bold=index == 0, max_width=w - label_w - 16)
