"""Dashboard reports: definitions, preview, instant runs, schedules, archive downloads."""
import threading
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..domain import DomainError
from ..reporting import logos, service
from ..security import authenticate
from ..timerange import TimeRangeError, resolve_range
from .deps import editor, settings_of, viewer_write

router = APIRouter()
TURKISH_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosuCGIOSUaiu")
# PDF/Excel renders run inside web workers; bound how many can run at once.
HEAVY_RENDERS = threading.BoundedSemaphore(2)


class _heavy:
    def __enter__(self):
        if not HEAVY_RENDERS.acquire(timeout=5):
            raise HTTPException(429, "Sunucu şu anda başka raporlar üretiyor; birkaç saniye sonra tekrar deneyin")

    def __exit__(self, *exc):
        HEAVY_RENDERS.release()
MEDIA = {"pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "csv": "text/csv; charset=utf-8", "manifest": "application/json"}


class ReportIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    dashboard_uid: str
    description: str = ""
    time_range: dict = Field(default_factory=lambda: {"from": "now-24h", "to": "now"})
    timezone: str = "Europe/Istanbul"
    variables: dict = Field(default_factory=dict)
    split_by: str | None = None
    panel_ids: list[int] = Field(default_factory=list)
    include_collapsed: bool = True
    layout: str = "grid"
    orientation: str = "landscape"
    paper: str = "A4"
    formats: list[str] = Field(default_factory=lambda: ["pdf"])
    cover: bool = True
    toc: bool = True
    footer_text: str = ""
    logo_id: str | None = Field(default=None, max_length=64)
    logo_on_cover: bool = True
    logo_on_pages: bool = True
    table_max_rows: int = 500
    send_partial: bool = False
    email_subject: str = ""
    email_message: str = ""


class RunIn(BaseModel):
    time_range: dict | None = None
    recipients: list[str] = Field(default_factory=list, max_length=50)


class ScheduleIn(BaseModel):
    cadence: str = "daily"
    timezone: str = "Europe/Istanbul"
    hour: int = 8
    minute: int = 0
    weekday: int = 0
    month_day: int = 1
    range_mode: str = "previous_period"
    recipients: list[str] = Field(default_factory=list, max_length=100)
    enabled: bool = False


class PreviewIn(ReportIn):
    max_sections: int = Field(default=3, ge=1, le=20)
    format: str = "pdf"


class DashboardExportIn(BaseModel):
    dashboard_uid: str
    time_range: dict = Field(default_factory=lambda: {"from": "now-6h", "to": "now"})
    timezone: str = "Europe/Istanbul"
    variables: dict = Field(default_factory=dict)
    format: str = "pdf"
    layout: str = "grid"
    orientation: str = "landscape"


def _fail(exc):
    status = 404 if "bulunamadı" in str(exc) else 409 if "bütünlüğü" in str(exc) or "uyuşmuyor" in str(exc) else 422
    raise HTTPException(status, str(exc)) from exc


def content_disposition(name, fmt):
    """RFC 6266: ASCII fallback plus UTF-8 filename* (Turkish names are not latin-1 safe)."""
    readable = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in name).strip()[:80] or "rapor"
    ascii_name = readable.translate(TURKISH_ASCII).encode("ascii", "ignore").decode() or "rapor"
    return f"attachment; filename=\"{ascii_name}.{fmt}\"; filename*=UTF-8''{quote(f'{readable}.{fmt}')}"


def _file_response(payload, fmt, name):
    return Response(payload, media_type=MEDIA.get(fmt, "application/octet-stream"),
                    headers={"Content-Disposition": content_disposition(name, fmt)})


@router.get("/api/dash-reports")
def list_reports(request: Request, user=Depends(authenticate)):
    return service.list_reports(settings_of(request), user)


@router.get("/api/dash-reports/{report_id}")
def get_report(report_id: str, request: Request, user=Depends(authenticate)):
    try:
        return service.get_report(settings_of(request), report_id, user)
    except DomainError as exc:
        _fail(exc)


@router.post("/api/dash-reports", status_code=201)
def create_report(body: ReportIn, request: Request, user=Depends(editor)):
    try:
        return service.save_report(settings_of(request), user, body.model_dump())
    except DomainError as exc:
        _fail(exc)


@router.put("/api/dash-reports/{report_id}")
def update_report(report_id: str, body: ReportIn, request: Request, user=Depends(editor)):
    try:
        return service.save_report(settings_of(request), user, body.model_dump(), report_id)
    except DomainError as exc:
        _fail(exc)


@router.delete("/api/dash-reports/{report_id}")
def delete_report(report_id: str, request: Request, user=Depends(editor)):
    try:
        service.delete_report(settings_of(request), user, report_id)
    except DomainError as exc:
        _fail(exc)
    return {"deleted": report_id}


class LogoIn(BaseModel):
    data: str = Field(min_length=8, max_length=1_400_000)


@router.post("/api/dash-reports/logos", status_code=201)
def upload_logo(body: LogoIn, request: Request, user=Depends(editor)):
    """Store a customer logo (validated and re-encoded as PNG); returns its id for the report config."""
    try:
        return logos.save(settings_of(request), body.data)
    except DomainError as exc:
        _fail(exc)


@router.get("/api/dash-reports/logos/{logo_id}")
def get_logo(logo_id: str, request: Request, user=Depends(authenticate)):
    try:
        target = logos.path(settings_of(request), logo_id)
    except DomainError as exc:
        _fail(exc)
    return FileResponse(target, media_type="image/png")


@router.post("/api/dash-reports/preview")
def preview(body: PreviewIn, request: Request, user=Depends(editor)):
    """Synchronous render (first N sections) without archiving — for the report editor."""
    settings = settings_of(request)
    try:
        config = service.validate_config(body.model_dump(), settings, user)
        start, end = resolve_range(config["time_range"]["from"], config["time_range"]["to"], config["timezone"])
        fmt = body.format if body.format in service.FORMATS else "pdf"
        from ..reporting.collect import collect
        from ..reporting.excel import render_csv, render_xlsx
        from ..reporting.pdf import render_pdf
        from .. import dashboards
        dashboard = dashboards.get(settings, config["dashboard_uid"], user)["dashboard"]
        renderer = {"pdf": render_pdf, "xlsx": render_xlsx, "csv": render_csv}[fmt]
        with _heavy():
            collected = collect(settings, dashboard, config, start, end, user=user["username"],
                                section_limit=body.max_sections)
            extra = {"logo": service.report_logo(settings, config)} if fmt == "pdf" else {}
            payload = renderer(config, collected, f"{config['name']} (önizleme)", **extra)
        dashboards.get(settings, config["dashboard_uid"], user)
    except (DomainError, TimeRangeError) as exc:
        _fail(exc)
    return _file_response(payload, fmt, f"{config['name']}-onizleme")


@router.post("/api/dashboards/export")
def export_dashboard(body: DashboardExportIn, request: Request, user=Depends(viewer_write)):
    """One-click 'download this dashboard as PDF/Excel' with the current time range and variables."""
    settings = settings_of(request)
    from .. import dashboards
    try:
        dashboard = dashboards.get(settings, body.dashboard_uid, user)["dashboard"]
        config = service.validate_config({"name": dashboard["title"], "dashboard_uid": body.dashboard_uid,
                                          "time_range": body.time_range, "timezone": body.timezone,
                                          "variables": body.variables, "layout": body.layout, "orientation": body.orientation,
                                          "formats": [body.format], "cover": False, "toc": False}, settings, user)
        start, end = resolve_range(config["time_range"]["from"], config["time_range"]["to"], config["timezone"])
        with _heavy():
            _, outputs, _ = service.build_outputs(settings, config, dashboard["title"], start, end,
                                                  user=user["username"], formats=[config["formats"][0]],
                                                  trusted=user["role"] in ("admin", "editor"), principal=user)
    except (DomainError, TimeRangeError) as exc:
        _fail(exc)
    fmt = config["formats"][0]
    return _file_response(outputs[fmt], fmt, dashboard["title"])


@router.post("/api/dash-reports/{report_id}/runs")
def run_report(report_id: str, body: RunIn, request: Request, user=Depends(editor)):
    try:
        return service.request_run(settings_of(request), user, report_id, body.model_dump())
    except DomainError as exc:
        _fail(exc)


def _visible_deliveries(runs, user):
    """Recipient lists are personal data; only report editors see them."""
    if user["role"] in ("admin", "editor"):
        return runs
    return [{**run, "recipients": [], "recipients_json": "[]"} for run in runs]


@router.get("/api/dash-reports/{report_id}/runs")
def report_runs(report_id: str, request: Request, user=Depends(authenticate)):
    return _visible_deliveries(service.list_runs(settings_of(request), report_id, user=user), user)


@router.get("/api/report-runs")
def all_runs(request: Request, limit: int = 200, user=Depends(authenticate)):
    return _visible_deliveries(service.list_runs(settings_of(request), None, limit, user=user), user)


@router.get("/api/report-runs/{run_id}/files/{kind}")
def download(run_id: str, kind: str, request: Request, user=Depends(authenticate)):
    if kind not in MEDIA:
        raise HTTPException(404, "Not found")
    try:
        path, filename = service.verified_file(settings_of(request), run_id, kind, user)
    except DomainError as exc:
        _fail(exc)
    return FileResponse(path, filename=filename, media_type=MEDIA[kind])


@router.get("/api/dash-reports/{report_id}/schedules")
def schedules(report_id: str, request: Request, user=Depends(authenticate)):
    return _visible_deliveries(service.list_schedules(settings_of(request), report_id, user), user)


@router.get("/api/report-schedules")
def all_schedules(request: Request, user=Depends(authenticate)):
    return _visible_deliveries(service.list_schedules(settings_of(request), user=user), user)


@router.post("/api/dash-reports/{report_id}/schedules", status_code=201)
def add_schedule(report_id: str, body: ScheduleIn, request: Request, user=Depends(editor)):
    try:
        return service.save_schedule(settings_of(request), user, report_id, body.model_dump())
    except DomainError as exc:
        _fail(exc)


@router.put("/api/dash-reports/{report_id}/schedules/{schedule_id}")
def update_schedule(report_id: str, schedule_id: str, body: ScheduleIn, request: Request, user=Depends(editor)):
    try:
        return service.save_schedule(settings_of(request), user, report_id, body.model_dump(), schedule_id)
    except DomainError as exc:
        _fail(exc)


@router.delete("/api/report-schedules/{schedule_id}")
def remove_schedule(schedule_id: str, request: Request, user=Depends(editor)):
    try:
        service.delete_schedule(settings_of(request), user, schedule_id)
    except DomainError as exc:
        _fail(exc)
    return {"deleted": schedule_id}
