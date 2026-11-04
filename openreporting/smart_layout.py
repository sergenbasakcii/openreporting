"""Smart dashboards: page-based layout (what you see on the A4/A3 canvas is what the PDF prints).

A smart dashboard is an ordinary dashboard with a ``smart`` block and a ``smartPos`` on each panel:

    smart    = {"version": 1, "paper": "A4", "orientation": "portrait", "rows": 32, "pages": 2,
                "cover": False, "subtitle": "..."}
    smartPos = {"page": 0, "x": 0, "y": 0, "w": 12, "h": 8}   # 24 columns × `rows` rows per page

``gridPos`` is derived from ``smartPos`` (page-stacked), so the same dashboard also opens in the
normal dashboard view, in reports and in schedules without special cases.
"""

import re

COLUMNS = 24
_LOGO = re.compile(r"^[0-9a-f]{64}$")
ROWS = {"portrait": 32, "landscape": 20}
MAX_PAGES = 50
PAPERS = ("A4", "A3", "Letter")


def _int(value, low, high, default):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def normalize(model):
    """Clamp the smart block and every panel position in place-safe copies; returns the model."""
    smart = model.get("smart")
    if not isinstance(smart, dict):
        model.pop("smart", None)
        return model
    orientation = "landscape" if smart.get("orientation") == "landscape" else "portrait"
    rows = ROWS[orientation]
    panels = model.get("panels") or []
    positions = [p.get("smartPos") if isinstance(p.get("smartPos"), dict) else {} for p in panels]
    used_pages = max((_int(pos.get("page"), 0, MAX_PAGES - 1, 0) for pos in positions), default=0) + 1
    clean = {
        "version": 1,
        "paper": smart.get("paper") if smart.get("paper") in PAPERS else "A4",
        "orientation": orientation,
        "rows": rows,
        "pages": _int(smart.get("pages"), used_pages, MAX_PAGES, used_pages),
        "cover": bool(smart.get("cover", False)),
        "subtitle": str(smart.get("subtitle") or "")[:200],
        "logo_id": smart.get("logo_id") if isinstance(smart.get("logo_id"), str) and _LOGO.match(smart["logo_id"]) else None,
        "logo_on_pages": bool(smart.get("logo_on_pages", True)),
        "footer": str(smart.get("footer") or "")[:160],
        "filters": bool(smart.get("filters", False)),
        "watermark": str(smart.get("watermark") or "")[:40],
    }
    for panel, pos in zip(panels, positions):
        w = _int(pos.get("w"), 2, COLUMNS, 12)
        h = _int(pos.get("h"), 2, rows, 8)
        x = _int(pos.get("x"), 0, COLUMNS - w, 0)
        y = _int(pos.get("y"), 0, rows - h, 0)
        page = _int(pos.get("page"), 0, clean["pages"] - 1, 0)
        panel["smartPos"] = {"page": page, "x": x, "y": y, "w": w, "h": h}
        panel["gridPos"] = {"x": x, "y": page * rows + y, "w": w, "h": h}
    model["smart"] = clean
    return model


def is_smart(dashboard):
    return isinstance((dashboard or {}).get("smart"), dict)


def report_overrides(dashboard):
    """Report/export settings implied by a smart dashboard (paper, orientation, cover, grid layout)."""
    smart = dashboard["smart"]
    overrides = {"paper": smart["paper"], "orientation": smart["orientation"], "layout": "grid", "cover": smart["cover"], "toc": False}
    overrides["logo_on_pages"] = smart.get("logo_on_pages", True)
    if smart.get("footer"):
        overrides["footer_text"] = smart["footer"]
    if smart.get("watermark"):
        overrides["watermark"] = smart["watermark"]
    return overrides


def plan(panels, rows, col_w, page_h):
    """PDF placements: (page_index, result, x, top, w, h) honoring each panel's smartPos exactly."""
    unit = page_h / rows
    placements = []
    for result in sorted(panels, key=lambda r: (r.panel["smartPos"]["page"], r.panel["smartPos"]["y"], r.panel["smartPos"]["x"])):
        pos = result.panel["smartPos"]
        placements.append((pos["page"], result, pos["x"] * col_w, pos["y"] * unit, pos["w"] * col_w, pos["h"] * unit))
    pages = max((p[0] for p in placements), default=0) + 1
    return placements, pages
