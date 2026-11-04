"""Table model, column sizing and paginated table drawing."""

from datetime import datetime, timezone
from ..units import resolve_unit
from .fieldcfg import contrast, display_name, field_config, fmt, mapped, threshold_color, color as named_color
from .pdf_base import (
    INK,
    FAINT,
    TINT,
    BRAND_INK,
    _rgb,
)


class TablesMixin:
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
