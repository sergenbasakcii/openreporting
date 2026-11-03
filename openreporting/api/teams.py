"""Teams (user groups) and per-dashboard permissions."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .. import dashboard_access, teams
from .deps import admin, admin_read, settings_of

router = APIRouter(tags=["Takımlar ve izinler"])


class TeamIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=300)


class MembersIn(BaseModel):
    user_ids: list[str] = Field(default_factory=list, max_length=teams.MAX_MEMBERS)


class DashboardGrantIn(BaseModel):
    principal_type: Literal["user", "team"]
    principal_id: str = Field(min_length=1, max_length=64)
    permission: Literal["view", "edit"]


class DashboardPolicyIn(BaseModel):
    restricted: bool
    revision: int = Field(ge=0)
    grants: list[DashboardGrantIn] = Field(default_factory=list, max_length=1000)


@router.get("/api/teams", summary="Takımları ve üyelerini listele")
def list_teams(request: Request, user=Depends(admin_read)):
    return teams.list_teams(settings_of(request))


@router.post("/api/teams", status_code=201, summary="Takım oluştur")
def create_team(body: TeamIn, request: Request, user=Depends(admin)):
    return teams.create(settings_of(request), user["id"], body.name, body.description)


@router.put("/api/teams/{team_id}", summary="Takımı yeniden adlandır")
def update_team(team_id: str, body: TeamIn, request: Request, user=Depends(admin)):
    teams.update(settings_of(request), user["id"], team_id, body.name, body.description)
    return {"ok": True}


@router.delete("/api/teams/{team_id}", summary="Takımı sil (izinleri de kalkar)")
def delete_team(team_id: str, request: Request, user=Depends(admin)):
    teams.delete(settings_of(request), user["id"], team_id)
    return {"ok": True}


@router.put("/api/teams/{team_id}/members", summary="Takım üyelerini ayarla")
def set_members(team_id: str, body: MembersIn, request: Request, user=Depends(admin)):
    return teams.set_members(settings_of(request), user["id"], team_id, body.user_ids)


@router.get("/api/dashboards/uid/{uid}/permissions", summary="Dashboard izinlerini oku")
def dashboard_permissions(uid: str, request: Request, user=Depends(admin_read)):
    return dashboard_access.policy(settings_of(request), user, uid)


@router.put("/api/dashboards/uid/{uid}/permissions", summary="Dashboard izinlerini değiştir")
def save_dashboard_permissions(uid: str, body: DashboardPolicyIn, request: Request, user=Depends(admin)):
    return dashboard_access.replace_policy(settings_of(request), user, uid, body.model_dump())
