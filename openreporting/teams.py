"""Teams (user groups): named sets of users that folder and dashboard permissions can be granted to."""

import re
import uuid

from fastapi import HTTPException

from .db import audit, connect, transaction, utcnow

MAX_MEMBERS = 5000
_NAME = re.compile(r"^[^\x00-\x1f]{2,80}$")


def _clean(name, description):
    name = str(name or "").strip()
    if not _NAME.match(name):
        raise HTTPException(422, "Takım adı 2-80 karakter olmalı")
    return name, str(description or "").strip()[:300]


def list_teams(settings):
    with connect(settings) as db:
        teams = [dict(r) for r in db.execute("SELECT id,name,description,created_at FROM teams ORDER BY LOWER(name)")]
        members = {}
        for row in db.execute(
            """SELECT m.team_id,u.id,u.username,u.display_name,u.role,u.active FROM team_members m
               JOIN users u ON u.id=m.user_id ORDER BY LOWER(u.username)"""
        ):
            members.setdefault(row["team_id"], []).append({k: row[k] for k in ("id", "username", "display_name", "role", "active")})
    for team in teams:
        team["members"] = members.get(team["id"], [])
    return teams


def create(settings, actor, name, description=""):
    name, description = _clean(name, description)
    team_id = str(uuid.uuid4())
    with connect(settings) as db, transaction(db):
        if db.execute("SELECT 1 FROM teams WHERE LOWER(name)=LOWER(?)", (name,)).fetchone():
            raise HTTPException(409, "Bu adla bir takım zaten var")
        db.execute("INSERT INTO teams(id,name,description,created_at,created_by) VALUES(?,?,?,?,?)", (team_id, name, description, utcnow(), actor))
        audit(db, actor, "team.created", "team", team_id, {"name": name})
    return {"id": team_id, "name": name, "description": description, "members": []}


def update(settings, actor, team_id, name, description=""):
    name, description = _clean(name, description)
    with connect(settings) as db, transaction(db):
        if db.execute("SELECT 1 FROM teams WHERE LOWER(name)=LOWER(?) AND id<>?", (name, team_id)).fetchone():
            raise HTTPException(409, "Bu adla bir takım zaten var")
        if not db.execute("UPDATE teams SET name=?,description=? WHERE id=?", (name, description, team_id)).rowcount:
            raise HTTPException(404, "Takım bulunamadı")
        audit(db, actor, "team.updated", "team", team_id, {"name": name})


def delete(settings, actor, team_id):
    with connect(settings) as db, transaction(db):
        row = db.execute("SELECT name FROM teams WHERE id=?", (team_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Takım bulunamadı")
        # Grants and memberships go with the team (ON DELETE CASCADE); access only ever shrinks.
        db.execute("DELETE FROM teams WHERE id=?", (team_id,))
        # dashboard_grants names principals of two kinds, so it cannot carry a foreign key.
        db.execute("DELETE FROM dashboard_grants WHERE principal_type='team' AND principal_id=?", (team_id,))
        audit(db, actor, "team.deleted", "team", team_id, {"name": row["name"]})


def set_members(settings, actor, team_id, user_ids):
    ids = list(dict.fromkeys(str(u) for u in user_ids))
    if len(ids) > MAX_MEMBERS:
        raise HTTPException(422, f"Bir takımda en fazla {MAX_MEMBERS} üye olabilir")
    with connect(settings) as db, transaction(db):
        if not db.execute("SELECT 1 FROM teams WHERE id=?", (team_id,)).fetchone():
            raise HTTPException(404, "Takım bulunamadı")
        for user_id in ids:
            if not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
                raise HTTPException(422, "Listede bulunmayan bir kullanıcı var")
        before = {r["user_id"] for r in db.execute("SELECT user_id FROM team_members WHERE team_id=?", (team_id,))}
        db.execute("DELETE FROM team_members WHERE team_id=?", (team_id,))
        for user_id in ids:
            db.execute("INSERT INTO team_members(team_id,user_id) VALUES(?,?)", (team_id, user_id))
        added, removed = sorted(set(ids) - before), sorted(before - set(ids))
        audit(db, actor, "team.members_changed", "team", team_id, {"added": added, "removed": removed})
    return {"added": len(added), "removed": len(removed)}


def teams_of(db, user_id):
    return [
        dict(r)
        for r in db.execute("SELECT t.id,t.name FROM teams t JOIN team_members m ON m.team_id=t.id WHERE m.user_id=? ORDER BY LOWER(t.name)", (user_id,))
    ]
