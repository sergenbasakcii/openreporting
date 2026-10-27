"""Excel (openpyxl) and CSV exports of the exact report data (all rows, no chart sampling)."""
import csv
import io
import re
from datetime import datetime, timezone

from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from ..query_engine import local_midnight_ms
from ..series_functions import bucketize
from ..timerange import zone
from ..units import resolve_unit
from .collect import variable_summary
from .fieldcfg import display_name

MAX_SHEETS = 250
MAX_ROWS_PER_SHEET = 1_000_000


def _safe(value):
    """Strip characters Excel cannot store and neutralise formula injection in text cells."""
    if isinstance(value, str):
        value = ILLEGAL_CHARACTERS_RE.sub("", value)
        if value[:1] in ("=", "+", "-", "@", "\t", "\r"):
            return "'" + value
    return value


def _sheet_title(text, used):
    base = re.sub(r"[\[\]\*\?/\\:]", " ", ILLEGAL_CHARACTERS_RE.sub("", text or "Panel")).strip()
    base = base.lstrip("=+-@'").strip()[:28] or "Panel"
    title = base
    counter = 2
    while title.lower() in used:
        title = f"{base[:25]} {counter}"
        counter += 1
    used.add(title.lower())
    return title


def panel_tables(result, tz, anchor_ms=0):
    """Yield (title, headers, rows, units) blocks for a panel result.

    Series are aligned to the panel's query interval before they are joined on
    time; joining raw per-host timestamps would explode into mostly empty cells.
    """
    blocks = []
    tzinfo = zone(tz)
    for frame in result.frames:
        if frame["type"] == "table":
            headers = [c["name"] for c in frame["columns"]]
            units = [c.get("unit", "") for c in frame["columns"]]
            rows = []
            for row in frame["rows"]:
                rows.append([datetime.fromtimestamp(v / 1000, timezone.utc).astimezone(tzinfo).replace(tzinfo=None)
                             if c["type"] == "time" and v is not None else v for v, c in zip(row, frame["columns"])])
            blocks.append((frame.get("name") or "Tablo", headers, rows, units))
    series = [f for f in result.frames if f["type"] == "timeseries"]
    if series:
        step = int(getattr(result, "interval_ms", 0) or 0)
        aligned = [bucketize(f["points"], step, "avg", anchor_ms) if step > 0 else f["points"] for f in series]
        stamps = sorted({p[0] for points in aligned for p in points})
        lookups = [dict(points) for points in aligned]
        headers = ["Zaman"] + [display_name(f) for f in series]
        units = [""] + [resolve_unit(None, f.get("unit")) for f in series]
        rows = [[datetime.fromtimestamp(t / 1000, timezone.utc).astimezone(tzinfo).replace(tzinfo=None)] +
                [lk.get(t) for lk in lookups] for t in stamps]
        blocks.append(("Zaman serileri", headers, rows, units))
    return blocks


def render_xlsx(config, collected, title):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    anchor = local_midnight_ms(collected.start, collected.timezone)
    summary = wb.active
    summary.title = "Özet"
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="1F2937")
    head_font = Font(bold=True, color="FFFFFF")
    tz = zone(collected.timezone)
    summary.append(["OpenReporting raporu", _safe(title)])
    summary["A1"].font = Font(bold=True, size=14)
    summary.append(["Dashboard", _safe(collected.dashboard.get("title", ""))])
    summary.append(["Dönem başlangıcı", collected.start.astimezone(tz).replace(tzinfo=None)])
    summary.append(["Dönem bitişi", collected.end.astimezone(tz).replace(tzinfo=None)])
    summary.append(["Saat dilimi", collected.timezone])
    summary.append(["Kısmi veri", "EVET" if collected.partial else "Hayır"])
    for name, value in variable_summary(collected.variables):
        summary.append([f"${name}", _safe(value)])
    summary.append([])
    summary.append(["Bölüm", "Panel", "Tür", "Durum", "Sayfa"])
    for cell in summary[summary.max_row]:
        cell.font = head_font
        cell.fill = head_fill
    used = {"özet"}
    sheets = 0
    for section in collected.sections:
        for result in section.panels:
            kind = result.panel.get("type")
            if kind in ("row", "text"):
                continue
            status = "; ".join(result.errors) or "; ".join(result.warnings) or "Tamam"
            blocks = panel_tables(result, collected.timezone, anchor)
            sheet_name = ""
            if blocks and sheets < MAX_SHEETS:
                sheet_name = _sheet_title(f"{section.title + ' ' if section.title else ''}{result.title}", used)
                ws = wb.create_sheet(sheet_name)
                sheets += 1
                ws.append([_safe(f"{section.title} · {result.title}" if section.title else result.title)])
                ws["A1"].font = Font(bold=True, size=12)
                for block_title, headers, rows, units in blocks:
                    ws.append([])
                    ws.append([_safe(block_title)])
                    ws.cell(ws.max_row, 1).font = bold
                    ws.append([_safe(f"{h} ({u})" if u and u not in ("short", "none") else h) for h, u in zip(headers, units)])
                    for cell in ws[ws.max_row]:
                        cell.font = head_font
                        cell.fill = head_fill
                    for row in rows[:MAX_ROWS_PER_SHEET]:
                        ws.append([_safe(v) for v in row])
                for col in range(1, (max(len(b[1]) for b in blocks) if blocks else 1) + 1):
                    ws.column_dimensions[get_column_letter(col)].width = 22 if col == 1 else 18
                for row in ws.iter_rows(min_row=1, max_row=ws.max_row):
                    for cell in row:
                        if isinstance(cell.value, datetime):
                            cell.number_format = "yyyy-mm-dd hh:mm"
                        elif isinstance(cell.value, float):
                            cell.number_format = "#,##0.###"
                ws.freeze_panes = "A5"
            summary.append([_safe(section.title or "—"), _safe(result.title or kind), _safe(kind), _safe(status[:300]),
                            _safe(sheet_name) or "—"])
    for col, width in zip("ABCDE", (28, 46, 14, 60, 28)):
        summary.column_dimensions[col].width = width
    for row in summary.iter_rows(min_row=1, max_row=6):
        row[0].font = bold
        if isinstance(row[1].value, datetime):
            row[1].number_format = "yyyy-mm-dd hh:mm"
        row[1].alignment = Alignment(horizontal="left")
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def render_csv(config, collected, title):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["bolum", "panel", "blok", "satir", "sutun", "deger", "birim"])
    tz = collected.timezone
    anchor = local_midnight_ms(collected.start, tz)
    for section in collected.sections:
        for result in section.panels:
            if result.panel.get("type") in ("row", "text"):
                continue
            for block_title, headers, rows, units in panel_tables(result, tz, anchor):
                for index, row in enumerate(rows):
                    key = row[0].isoformat() if isinstance(row[0], datetime) else row[0]
                    for column, value, unit in list(zip(headers, row, units))[1:]:
                        if value is None and block_title == "Zaman serileri":
                            continue  # long format: a missing sample is simply absent
                        writer.writerow([_safe(section.title), _safe(result.title), _safe(block_title), _safe(key), _safe(column),
                                         "" if value is None else (value.isoformat() if isinstance(value, datetime) else _safe(value)),
                                         _safe(unit)])
    return out.getvalue().encode("utf-8-sig")
