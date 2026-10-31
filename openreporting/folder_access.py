"""Content authorization for one installation; datasource privileges remain global.

An omitted principal can read shared content only. Never use an implicit system
administrator: workers carry the current initiating/approving account instead.
"""
from fastapi import HTTPException

from .db import audit, connect, transaction, utcnow


def principal(db, user):
    if not user:
        return None
    row = db.execute("SELECT id,username,role,active FROM users WHERE id=?", (user["id"],)).fetchone()
    return dict(row) if row and row["active"] else None


def visible_sql(db, user, column, *, edit=False):
    """Return a parameterized predicate for an internal, fixed folder-id column.

    Applied before ordering/limits so inaccessible content cannot crowd out rows.
    """
    actor = principal(db, user)
    if user and not actor:
        return "1=0", []
    if edit and (not actor or actor["role"] not in ("admin", "editor")):
        return "1=0", []
    if actor and actor["role"] == "admin":
        return "1=1", []
    permission = " AND g.permission='edit'" if edit else ""
    predicate = f"({column} IS NULL OR NOT EXISTS(SELECT 1 FROM folder_policy p WHERE p.folder_id={column} AND p.restricted=1)"
    params = []
    if actor:
        predicate += f" OR EXISTS(SELECT 1 FROM folder_user_grants g WHERE g.folder_id={column} AND g.user_id=?{permission})"
        params.append(actor["id"])
    return predicate + ")", params


def allowed(db, user, folder_id, *, edit=False):
    sql, params = visible_sql(db, user, "f.folder_id", edit=edit)
    return bool(db.execute(f"SELECT 1 FROM (SELECT CAST(? AS TEXT) AS folder_id) f WHERE {sql}", [folder_id, *params]).fetchone())


def require_folder(db, user, folder_id, *, edit=False):
    if not allowed(db, user, folder_id, edit=edit):
        raise HTTPException(404, "İçerik bulunamadı veya erişim izniniz yok")


def require_dashboard(db, user, uid, *, edit=False):
    row = db.execute("SELECT * FROM dashboards WHERE uid=?", (uid,)).fetchone()
    if not row:
        raise HTTPException(404, "Dashboard bulunamadı")
    require_folder(db, user, row["folder_id"], edit=edit)
    return row


def require_report(db, user, report_id, *, edit=False):
    row = db.execute("SELECT * FROM dash_reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Rapor bulunamadı")
    require_dashboard(db, user, row["dashboard_uid"], edit=edit)
    return row


def _admin(db, user):
    actor = principal(db, user)
    if not actor or actor["role"] != "admin":
        raise HTTPException(403, "Klasör izinlerini yalnızca yönetici değiştirebilir")


def policy(settings, user, uid):
    with connect(settings) as db:
        _admin(db, user)
        folder = db.execute("SELECT id FROM folders WHERE uid=?", (uid,)).fetchone()
        if not folder:
            raise HTTPException(404, "Klasör bulunamadı")
        row = db.execute("SELECT restricted,revision FROM folder_policy WHERE folder_id=?", (folder["id"],)).fetchone()
        grants = [dict(r) for r in db.execute("""SELECT g.user_id,u.username,g.permission FROM folder_user_grants g
            JOIN users u ON u.id=g.user_id WHERE g.folder_id=? ORDER BY u.username""", (folder["id"],))]
        return {"restricted": bool(row and row["restricted"]), "revision": row["revision"] if row else 0, "grants": grants}


def replace_policy(settings, user, uid, body):
    grants = body["grants"]
    if len({g["user_id"] for g in grants}) != len(grants):
        raise HTTPException(422, "Aynı kullanıcı birden fazla eklenemez")
    with connect(settings) as db, transaction(db):
        _admin(db, user)
        folder = db.execute("SELECT id FROM folders WHERE uid=?", (uid,)).fetchone()
        if not folder:
            raise HTTPException(404, "Klasör bulunamadı")
        fid = folder["id"]
        db.execute("INSERT INTO folder_policy(folder_id,restricted,revision) VALUES(?,0,0) ON CONFLICT(folder_id) DO NOTHING", (fid,))
        for grant in grants:
            if grant["permission"] not in ("view", "edit") or not db.execute("SELECT 1 FROM users WHERE id=? AND active=1", (grant["user_id"],)).fetchone():
                raise HTTPException(422, "Etkin kullanıcı ve geçerli izin seçin")
        changed = db.execute("UPDATE folder_policy SET restricted=?,revision=revision+1 WHERE folder_id=? AND revision=?",
                             (int(body["restricted"]), fid, body["revision"]))
        if not changed.rowcount:
            raise HTTPException(409, "İzinler değişti; pencereyi yeniden açın")
        db.execute("DELETE FROM folder_user_grants WHERE folder_id=?", (fid,))
        for grant in grants:
            db.execute("INSERT INTO folder_user_grants(folder_id,user_id,permission) VALUES(?,?,?)", (fid, grant["user_id"], grant["permission"]))
        # Existing approvals must be reviewed after an access boundary changes.
        db.execute("""UPDATE dash_report_schedules SET enabled=0,updated_at=? WHERE report_id IN
            (SELECT r.id FROM dash_reports r JOIN dashboards d ON d.uid=r.dashboard_uid WHERE d.folder_id=?)""", (utcnow(), fid))
        audit(db, user["id"], "folder.permissions_changed", "folder", uid,
              {"restricted": body["restricted"], "revision": body["revision"] + 1, "grants": grants})
    return policy(settings, user, uid)
