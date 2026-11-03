"""Per-dashboard permissions: restrict one dashboard to chosen users and teams (view or edit)."""

from fastapi import HTTPException

from .db import audit, connect, transaction, utcnow

PERMISSIONS = ("view", "edit")
PRINCIPALS = ("user", "team")


def _admin(db, user):
    row = db.execute("SELECT role,active FROM users WHERE id=?", (user["id"],)).fetchone()
    if not row or not row["active"] or row["role"] != "admin":
        raise HTTPException(403, "Dashboard izinlerini yalnızca yönetici değiştirebilir")


def _dashboard(db, uid):
    row = db.execute("SELECT id,uid,title FROM dashboards WHERE uid=?", (uid,)).fetchone()
    if not row:
        raise HTTPException(404, "Dashboard bulunamadı")
    return row


def policy(settings, user, uid):
    with connect(settings) as db:
        _admin(db, user)
        dash = _dashboard(db, uid)
        row = db.execute("SELECT restricted,revision FROM dashboard_policy WHERE dashboard_id=?", (dash["id"],)).fetchone()
        grants = [
            dict(r)
            for r in db.execute(
                """SELECT g.principal_type,g.principal_id,g.permission,
                   COALESCE(u.username,t.name) AS name FROM dashboard_grants g
                   LEFT JOIN users u ON g.principal_type='user' AND u.id=g.principal_id
                   LEFT JOIN teams t ON g.principal_type='team' AND t.id=g.principal_id
                   WHERE g.dashboard_id=? ORDER BY g.principal_type DESC, LOWER(COALESCE(u.username,t.name))""",
                (dash["id"],),
            )
        ]
    return {"restricted": bool(row and row["restricted"]), "revision": row["revision"] if row else 0, "grants": grants}


def replace_policy(settings, user, uid, body):
    grants = body["grants"]
    keys = {(g["principal_type"], g["principal_id"]) for g in grants}
    if len(keys) != len(grants):
        raise HTTPException(422, "Aynı kullanıcı veya takım birden fazla eklenemez")
    with connect(settings) as db, transaction(db):
        _admin(db, user)
        dash = _dashboard(db, uid)
        for grant in grants:
            kind, pid = grant["principal_type"], grant["principal_id"]
            if kind not in PRINCIPALS or grant["permission"] not in PERMISSIONS:
                raise HTTPException(422, "Geçerli kullanıcı/takım ve izin seçin")
            table, extra = ("users", " AND active=1") if kind == "user" else ("teams", "")
            if not db.execute(f"SELECT 1 FROM {table} WHERE id=?{extra}", (pid,)).fetchone():
                raise HTTPException(422, "Etkin kullanıcı veya var olan takım seçin")
        db.execute("INSERT INTO dashboard_policy(dashboard_id,restricted,revision) VALUES(?,0,0) ON CONFLICT(dashboard_id) DO NOTHING", (dash["id"],))
        changed = db.execute(
            "UPDATE dashboard_policy SET restricted=?,revision=revision+1 WHERE dashboard_id=? AND revision=?",
            (int(body["restricted"]), dash["id"], body["revision"]),
        )
        if not changed.rowcount:
            raise HTTPException(409, "İzinler değişti; pencereyi yeniden açın")
        db.execute("DELETE FROM dashboard_grants WHERE dashboard_id=?", (dash["id"],))
        for grant in grants:
            db.execute(
                "INSERT INTO dashboard_grants(dashboard_id,principal_type,principal_id,permission) VALUES(?,?,?,?)",
                (dash["id"], grant["principal_type"], grant["principal_id"], grant["permission"]),
            )
        # Scheduled deliveries were approved under the old boundary: they must be reviewed again.
        db.execute(
            "UPDATE dash_report_schedules SET enabled=0,updated_at=? WHERE report_id IN (SELECT id FROM dash_reports WHERE dashboard_uid=?)", (utcnow(), uid)
        )
        audit(
            db,
            user["id"],
            "dashboard.permissions_changed",
            "dashboard",
            uid,
            {"restricted": body["restricted"], "revision": body["revision"] + 1, "grants": grants},
        )
    return policy(settings, user, uid)
