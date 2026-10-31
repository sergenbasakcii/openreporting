"""Dashboards, folders, stars, versions, import and annotations."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import dashboard_runtime, dashboards, datasources, folder_access
from ..db import audit, connect, transaction, utcnow
from ..domain import DomainError, identity
from ..security import authenticate
from .deps import admin, admin_read, editor, settings_of, viewer_write

router = APIRouter()


class DashboardSaveIn(BaseModel):
    dashboard: dict
    folderUid: str | None = None
    message: str = Field(default="", max_length=500)
    overwrite: bool = False


class ImportIn(BaseModel):
    dashboard: dict
    folderUid: str | None = None
    overwrite: bool = False


class RestoreIn(BaseModel):
    version: int = Field(ge=1)


class FolderIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class AnnotationIn(BaseModel):
    dashboardUID: str | None = None
    panelId: int | None = None
    time: int
    timeEnd: int | None = None
    text: str = Field(min_length=1, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)


class ResolveIn(BaseModel):
    dashboard: dict = Field(default_factory=dict)
    uid: str | None = Field(default=None, max_length=40)
    overrides: dict = Field(default_factory=dict)
    range: dict = Field(default_factory=lambda: {"from": "now-6h", "to": "now"})
    timezone: str = "UTC"


def _fail(exc):
    status = 409 if isinstance(exc, dashboards.VersionConflict) else 404 if "bulunamadı" in str(exc) else 422
    raise HTTPException(status, str(exc)) from exc


@router.get("/api/search")
def search(request: Request, query: str = "", tag: str = "", folderUid: str | None = None, starred: bool = False,
           user=Depends(authenticate)):
    results = dashboards.search(settings_of(request), user, query[:200], tag[:50], folderUid, starred)
    return results


@router.get("/api/dashboards/tags")
def dashboard_tags(request: Request, user=Depends(authenticate)):
    return dashboards.tags(settings_of(request), user)


@router.get("/api/dashboards/uid/{uid}")
def get_dashboard(uid: str, request: Request, user=Depends(authenticate)):
    try:
        return dashboards.get(settings_of(request), uid, user)
    except DomainError as exc:
        _fail(exc)


@router.post("/api/dashboards/db")
def save_dashboard(body: DashboardSaveIn, request: Request, user=Depends(editor)):
    try:
        return dashboards.save(settings_of(request), user, body.dashboard, folder_uid=body.folderUid,
                               message=body.message, overwrite=body.overwrite)
    except DomainError as exc:
        _fail(exc)


@router.post("/api/dashboards/import")
def import_dashboard(body: ImportIn, request: Request, user=Depends(editor)):
    settings = settings_of(request)
    mapping = dashboards.import_map(datasources.list_all(settings), body.dashboard)
    try:
        folder = body.folderUid if body.folderUid is not None else dashboards.KEEP_FOLDER
        result = dashboards.save(settings, user, body.dashboard, folder_uid=folder,
                                 message="İçe aktarıldı", overwrite=body.overwrite, ds_map=mapping)
    except DomainError as exc:
        _fail(exc)
    return result


@router.delete("/api/dashboards/uid/{uid}")
def delete_dashboard(uid: str, request: Request, user=Depends(editor)):
    try:
        dashboards.delete(settings_of(request), user, uid)
    except DomainError as exc:
        _fail(exc)
    return {"deleted": uid}


@router.get("/api/dashboards/uid/{uid}/versions")
def dashboard_versions(uid: str, request: Request, user=Depends(authenticate)):
    try:
        return dashboards.versions(settings_of(request), uid, user)
    except DomainError as exc:
        _fail(exc)


@router.get("/api/dashboards/uid/{uid}/versions/{version}")
def dashboard_version(uid: str, version: int, request: Request, user=Depends(authenticate)):
    try:
        return dashboards.version_data(settings_of(request), uid, version, user)
    except DomainError as exc:
        _fail(exc)


@router.post("/api/dashboards/uid/{uid}/restore")
def restore_dashboard(uid: str, body: RestoreIn, request: Request, user=Depends(editor)):
    try:
        return dashboards.restore(settings_of(request), user, uid, body.version)
    except DomainError as exc:
        _fail(exc)


@router.post("/api/dashboards/variables/resolve")
def resolve_variables(body: ResolveIn, request: Request, user=Depends(viewer_write)):
    """Resolve all variables server-side (used by report preview and dashboard links)."""
    settings = settings_of(request)
    trusted = user["role"] in ("admin", "editor")
    try:
        if trusted:
            uid = body.uid or body.dashboard.get("uid")
            if uid:
                with connect(settings) as db:
                    if db.execute("SELECT 1 FROM dashboards WHERE uid=?", (uid,)).fetchone():
                        folder_access.require_dashboard(db, user, uid)
            model = dashboards.normalize(body.dashboard)
        elif body.uid:
            # Viewers resolve the saved definition; a posted dashboard body is ignored.
            model = dashboards.get(settings, body.uid, user)["dashboard"]
        else:
            raise HTTPException(403, "İzleyiciler yalnızca kayıtlı dashboard değişkenlerini çözebilir")
        variables, warnings = dashboard_runtime.resolve_variables(
            settings, model, body.overrides, {"range": body.range, "timezone": body.timezone},
            user=user["username"], trusted=trusted)
    except DomainError as exc:
        _fail(exc)
    return {"variables": variables, "warnings": warnings}


@router.post("/api/user/stars/dashboard/{uid}")
def star_dashboard(uid: str, request: Request, user=Depends(viewer_write)):
    try:
        dashboards.star(settings_of(request), user, uid, True)
    except DomainError as exc:
        _fail(exc)
    return {"starred": True}


@router.delete("/api/user/stars/dashboard/{uid}")
def unstar_dashboard(uid: str, request: Request, user=Depends(viewer_write)):
    try:
        dashboards.star(settings_of(request), user, uid, False)
    except DomainError as exc:
        _fail(exc)
    return {"starred": False}


@router.get("/api/folders")
def list_folders(request: Request, user=Depends(authenticate)):
    return dashboards.folders(settings_of(request), user)


@router.post("/api/folders", status_code=201)
def create_folder(body: FolderIn, request: Request, user=Depends(editor)):
    try:
        return dashboards.save_folder(settings_of(request), user, body.title)
    except DomainError as exc:
        _fail(exc)


@router.put("/api/folders/{uid}")
def rename_folder(uid: str, body: FolderIn, request: Request, user=Depends(editor)):
    try:
        return dashboards.save_folder(settings_of(request), user, body.title, uid)
    except DomainError as exc:
        _fail(exc)


@router.delete("/api/folders/{uid}")
def remove_folder(uid: str, request: Request, user=Depends(editor)):
    try:
        dashboards.delete_folder(settings_of(request), user, uid)
    except DomainError as exc:
        _fail(exc)
    return {"deleted": uid}


@router.get("/api/annotations")
def list_annotations(request: Request, dashboardUID: str = "", start: int = 0, end: int = 0,
                     user=Depends(authenticate)):
    with connect(settings_of(request)) as db:
        if dashboardUID:
            folder_access.require_dashboard(db, user, dashboardUID)
        rows = db.execute("""SELECT a.id,a.dashboard_uid,a.panel_id,a.time_ms,a.time_end_ms,a.text,a.tags_json,
                             a.created_at,u.username AS created_by FROM annotations a LEFT JOIN users u ON u.id=a.created_by
                             WHERE (a.dashboard_uid=? OR a.dashboard_uid IS NULL) AND a.time_ms<=? AND
                             COALESCE(a.time_end_ms,a.time_ms)>=? ORDER BY a.time_ms LIMIT 1000""",
                          (dashboardUID or None, end or 2**53, start)).fetchall()
    return [{**dict(r), "tags": json.loads(r["tags_json"])} for r in rows]


@router.post("/api/annotations", status_code=201)
def create_annotation(body: AnnotationIn, request: Request, user=Depends(editor)):
    if body.timeEnd is not None and body.timeEnd < body.time:
        raise HTTPException(422, "Annotation end precedes start")
    annotation_id = identity()
    with connect(settings_of(request)) as db, transaction(db):
        if body.dashboardUID:
            folder_access.require_dashboard(db, user, body.dashboardUID, edit=True)
        db.execute("INSERT INTO annotations VALUES(?,?,?,?,?,?,?,?,?)",
                   (annotation_id, body.dashboardUID, body.panelId, body.time, body.timeEnd, body.text,
                    json.dumps([t[:50] for t in body.tags]), utcnow(), user["id"]))
        audit(db, user["id"], "annotation.created", "annotation", annotation_id)
    return {"id": annotation_id}


@router.delete("/api/annotations/{annotation_id}")
def delete_annotation(annotation_id: str, request: Request, user=Depends(editor)):
    with connect(settings_of(request)) as db, transaction(db):
        row = db.execute("SELECT dashboard_uid FROM annotations WHERE id=?", (annotation_id,)).fetchone()
        if row and row["dashboard_uid"]:
            folder_access.require_dashboard(db, user, row["dashboard_uid"], edit=True)
        if not db.execute("DELETE FROM annotations WHERE id=?", (annotation_id,)).rowcount:
            raise HTTPException(404, "Annotation not found")
        audit(db, user["id"], "annotation.deleted", "annotation", annotation_id)
    return {"deleted": annotation_id}


class GrantIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=80)
    permission: str = Field(pattern="^(view|edit)$")


class FolderPolicyIn(BaseModel):
    restricted: bool
    revision: int = Field(ge=0)
    grants: list[GrantIn] = Field(default_factory=list, max_length=500)


@router.get("/api/folders/{uid}/permissions")
def folder_permissions(uid: str, request: Request, user=Depends(admin_read)):
    return folder_access.policy(settings_of(request), user, uid)


@router.put("/api/folders/{uid}/permissions")
def save_folder_permissions(uid: str, body: FolderPolicyIn, request: Request, user=Depends(admin)):
    return folder_access.replace_policy(settings_of(request), user, uid, body.model_dump())
