"""Content authorization for one installation; datasource privileges remain global.

Folders: unrestricted folders are visible to everyone; a restricted folder is visible to users granted
directly or through a team. Dashboards: an unrestricted dashboard follows its folder; a restricted
dashboard is visible only to its own user/team grants (this can both narrow a shared folder and share
one dashboard out of a restricted folder). Admins see everything.

An omitted principal can read shared content only. Never use an implicit system
administrator: workers carry the current initiating/approving account instead.
"""

from fastapi import HTTPException

from .db import audit, connect, transaction, utcnow

NOT_FOUND = "İçerik bulunamadı veya erişim izniniz yok"


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
        predicate += (
            f" OR EXISTS(SELECT 1 FROM folder_team_grants g JOIN team_members m ON m.team_id=g.team_id WHERE g.folder_id={column} AND m.user_id=?{permission})"
        )
        params += [actor["id"], actor["id"]]
    return predicate + ")", params


def visible_dashboards_sql(db, user, alias="d", *, edit=False):
    """Parameterized predicate over a dashboards row aliased `alias` (folder rules + dashboard policy)."""
    actor = principal(db, user)
    if user and not actor:
        return "1=0", []
    if edit and (not actor or actor["role"] not in ("admin", "editor")):
        return "1=0", []
    if actor and actor["role"] == "admin":
        return "1=1", []
    folder_sql, folder_params = visible_sql(db, user, f"{alias}.folder_id", edit=edit)
    restricted = f"EXISTS(SELECT 1 FROM dashboard_policy dp WHERE dp.dashboard_id={alias}.id AND dp.restricted=1)"
    predicate = f"((NOT {restricted} AND {folder_sql})"
    params = list(folder_params)
    if actor:
        permission = " AND dg.permission='edit'" if edit else ""
        predicate += (
            f" OR ({restricted} AND EXISTS(SELECT 1 FROM dashboard_grants dg WHERE dg.dashboard_id={alias}.id{permission} AND"
            " ((dg.principal_type='user' AND dg.principal_id=?) OR"
            " (dg.principal_type='team' AND dg.principal_id IN (SELECT team_id FROM team_members WHERE user_id=?)))))"
        )
        params += [actor["id"], actor["id"]]
    return predicate + ")", params


def dashboard_allowed(db, user, uid, *, edit=False):
    sql, params = visible_dashboards_sql(db, user, "d", edit=edit)
    return bool(db.execute(f"SELECT 1 FROM dashboards d WHERE d.uid=? AND {sql}", [uid, *params]).fetchone())


def allowed(db, user, folder_id, *, edit=False):
    sql, params = visible_sql(db, user, "f.folder_id", edit=edit)
    return bool(db.execute(f"SELECT 1 FROM (SELECT CAST(? AS TEXT) AS folder_id) f WHERE {sql}", [folder_id, *params]).fetchone())


def require_folder(db, user, folder_id, *, edit=False):
    if not allowed(db, user, folder_id, edit=edit):
        raise HTTPException(404, "İçerik bulunamadı veya erişim izniniz yok")


def require_dashboard(db, user, uid, *, edit=False):
    row = db.execute("SELECT * FROM dashboards WHERE uid=?", (uid,)).fetchone()
    if not row or not dashboard_allowed(db, user, uid, edit=edit):
        raise HTTPException(404, NOT_FOUND)
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
        grants = [
            dict(r)
            for r in db.execute(
                """SELECT g.user_id,u.username,g.permission FROM folder_user_grants g
            JOIN users u ON u.id=g.user_id WHERE g.folder_id=? ORDER BY u.username""",
                (folder["id"],),
            )
        ]
        team_grants = [
            dict(r)
            for r in db.execute(
                """SELECT g.team_id,t.name,g.permission FROM folder_team_grants g
            JOIN teams t ON t.id=g.team_id WHERE g.folder_id=? ORDER BY t.name""",
                (folder["id"],),
            )
        ]
        return {"restricted": bool(row and row["restricted"]), "revision": row["revision"] if row else 0, "grants": grants, "team_grants": team_grants}


def replace_policy(settings, user, uid, body):
    grants = body["grants"]
    team_grants = body.get("team_grants") or []
    if len({g["user_id"] for g in grants}) != len(grants) or len({g["team_id"] for g in team_grants}) != len(team_grants):
        raise HTTPException(422, "Aynı kullanıcı veya takım birden fazla eklenemez")
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
        for grant in team_grants:
            if grant["permission"] not in ("view", "edit") or not db.execute("SELECT 1 FROM teams WHERE id=?", (grant["team_id"],)).fetchone():
                raise HTTPException(422, "Var olan bir takım ve geçerli izin seçin")
        changed = db.execute(
            "UPDATE folder_policy SET restricted=?,revision=revision+1 WHERE folder_id=? AND revision=?", (int(body["restricted"]), fid, body["revision"])
        )
        if not changed.rowcount:
            raise HTTPException(409, "İzinler değişti; pencereyi yeniden açın")
        db.execute("DELETE FROM folder_user_grants WHERE folder_id=?", (fid,))
        for grant in grants:
            db.execute("INSERT INTO folder_user_grants(folder_id,user_id,permission) VALUES(?,?,?)", (fid, grant["user_id"], grant["permission"]))
        db.execute("DELETE FROM folder_team_grants WHERE folder_id=?", (fid,))
        for grant in team_grants:
            db.execute("INSERT INTO folder_team_grants(folder_id,team_id,permission) VALUES(?,?,?)", (fid, grant["team_id"], grant["permission"]))
        # Existing approvals must be reviewed after an access boundary changes.
        db.execute(
            """UPDATE dash_report_schedules SET enabled=0,updated_at=? WHERE report_id IN
            (SELECT r.id FROM dash_reports r JOIN dashboards d ON d.uid=r.dashboard_uid WHERE d.folder_id=?)""",
            (utcnow(), fid),
        )
        audit(
            db,
            user["id"],
            "folder.permissions_changed",
            "folder",
            uid,
            {"restricted": body["restricted"], "revision": body["revision"] + 1, "grants": grants, "team_grants": team_grants},
        )
    return policy(settings, user, uid)
