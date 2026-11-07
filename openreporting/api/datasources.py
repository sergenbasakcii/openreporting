"""Datasource administration and query endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import copy

from .. import dashboards, datasources, frames, query_engine, series_functions, transformations, units
from ..domain import DomainError
from ..datasources.base import DataSourceError
from ..security import authenticate
from .deps import admin, admin_read, editor, settings_of, viewer_write

router = APIRouter()


class DataSourceIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    type: str
    url: str = ""
    uid: str | None = None
    isDefault: bool = False
    jsonData: dict = Field(default_factory=dict)
    secureJsonData: dict = Field(default_factory=dict)
    secureJsonReset: list[str] = Field(default_factory=list)


class MetricFindIn(BaseModel):
    query: str | dict | None = None
    range: dict = Field(default_factory=lambda: {"from": "now-6h", "to": "now"})
    timezone: str = "UTC"
    variables: dict = Field(default_factory=dict)


class QueryIn(BaseModel):
    targets: list[dict] = Field(min_length=1, max_length=26)
    range: dict = Field(default_factory=lambda: {"from": "now-6h", "to": "now"})
    timezone: str = "UTC"
    maxDataPoints: int = Field(default=1000, ge=10, le=20000)
    minInterval: str | None = None
    datasource: dict | str | None = None
    variables: dict = Field(default_factory=dict)
    transformations: list[dict] = Field(default_factory=list, max_length=30)
    dashboardTitle: str = ""
    now: int | None = None
    dashboardUid: str | None = Field(default=None, max_length=40)
    panelId: int | None = None
    compare: str | None = Field(default=None, pattern="^previous$")


EDIT_ROLES = ("admin", "editor")


def viewer_payload(settings, body, user):
    """Viewers run the saved panel definition; only range/variables come from the browser."""
    if not body.dashboardUid or body.panelId is None:
        raise HTTPException(403, "İzleyiciler yalnızca kayıtlı dashboard panellerini sorgulayabilir")
    try:
        model = dashboards.get(settings, body.dashboardUid, user)["dashboard"]
    except DomainError as exc:
        raise HTTPException(404, str(exc)) from exc
    panel = dashboards.find_panel(model, body.panelId)
    if not panel or not panel.get("targets"):
        raise HTTPException(404, "Panel bulunamadı")
    payload = body.model_dump()
    payload.update(
        targets=copy.deepcopy(panel["targets"]),
        transformations=panel.get("transformations") or [],
        datasource=panel.get("datasource"),
        minInterval=panel.get("interval"),
        variables=dashboards.viewer_variables(model, body.variables),
        dashboardTitle=model.get("title", ""),
        compare=(panel.get("options") or {}).get("compare"),
    )
    return payload


@router.get("/api/datasources")
def list_datasources(request: Request, user=Depends(authenticate)):
    items = datasources.list_all(settings_of(request))
    if user["role"] == "admin":
        return items
    return [{"uid": d["uid"], "name": d["name"], "type": d["type"], "isDefault": d["isDefault"]} for d in items]


@router.get("/api/datasources/types")
def datasource_types(user=Depends(authenticate)):
    return {"types": datasources.TYPE_INFO, "categories": datasources.CATEGORIES, "testdataScenarios": datasources.scenarios()}


@router.get("/api/datasources/{uid}")
def get_datasource(uid: str, request: Request, user=Depends(admin_read)):
    record = datasources.load(settings_of(request), uid)
    if record is None:
        raise HTTPException(404, "Veri kaynağı bulunamadı")
    return datasources.public(record, settings_of(request))


@router.post("/api/datasources", status_code=201)
def create_datasource(body: DataSourceIn, request: Request, user=Depends(admin)):
    try:
        uid = datasources.save(settings_of(request), user["id"], body.model_dump())
    except DataSourceError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"uid": uid}


@router.put("/api/datasources/{uid}")
def update_datasource(uid: str, body: DataSourceIn, request: Request, user=Depends(admin)):
    try:
        datasources.save(settings_of(request), user["id"], body.model_dump(), uid=uid)
    except DataSourceError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"uid": uid}


@router.delete("/api/datasources/{uid}")
def delete_datasource(uid: str, request: Request, user=Depends(admin)):
    try:
        datasources.delete(settings_of(request), user["id"], uid)
    except DataSourceError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"deleted": uid}


@router.post("/api/datasources/{uid}/health")
def datasource_health(uid: str, request: Request, user=Depends(editor)):
    try:
        return datasources.get(settings_of(request), uid).health()
    except (DataSourceError, ValueError) as exc:
        return {"status": "error", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 - connection errors vary by driver
        return {"status": "error", "message": f"Bağlantı başarısız: {type(exc).__name__}"}


@router.post("/api/datasources/{uid}/metric-find")
def metric_find(uid: str, body: MetricFindIn, request: Request, user=Depends(editor)):
    try:
        values = query_engine.metric_find(
            settings_of(request), uid, body.query, {"range": body.range, "timezone": body.timezone, "variables": body.variables}, user=user["username"]
        )
    except (DataSourceError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"values": values[:10000], "truncated": len(values) > 10000}


@router.post("/api/ds/query")
def run_query(body: QueryIn, request: Request, user=Depends(viewer_write)):
    settings = settings_of(request)
    trusted = user["role"] in EDIT_ROLES
    if trusted and body.dashboardUid:
        dashboards.get(settings, body.dashboardUid, user)
    payload = body.model_dump() if trusted else viewer_payload(settings, body, user)
    try:
        return query_engine.run(settings, payload, user=user["username"], trusted=trusted)
    except (query_engine.QueryError, DataSourceError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/api/query/catalog")
def query_catalog(user=Depends(authenticate)):
    return {
        "functions": series_functions.CATALOG,
        "transformations": transformations.CATALOG,
        "reducers": [{"value": k, "label": v} for k, v in frames.REDUCERS.items()],
        "units": [{"group": group, "units": [{"value": v, "label": label} for v, label in entries]} for group, entries in units.UNIT_CATALOG.items()],
    }
