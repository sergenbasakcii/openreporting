"""Administration of service accounts and their API tokens (admin only; issuing needs step-up)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import api_tokens
from ..security import reauthenticate
from .deps import ReauthBody, admin, admin_read, settings_of

router = APIRouter(tags=["API anahtarları"])


class AccountIn(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    role: str = "viewer"
    display_name: str = Field(default="", max_length=120)


class AccountPatch(BaseModel):
    role: str | None = None
    active: bool | None = None


class TokenIn(ReauthBody):
    name: str = Field(min_length=2, max_length=80)
    days: int = Field(default=90, ge=1, le=api_tokens.MAX_DAYS)


def _fail(exc):
    raise HTTPException(422, str(exc)) from None


@router.get("/api/admin/service-accounts", summary="Servis hesaplarını ve anahtarlarını listele")
def list_accounts(request: Request, user=Depends(admin_read)):
    return api_tokens.list_accounts(settings_of(request))


@router.post("/api/admin/service-accounts", status_code=201, summary="Servis hesabı oluştur")
def create_account(body: AccountIn, request: Request, user=Depends(admin)):
    try:
        return api_tokens.create_account(settings_of(request), user["id"], body.username, body.role, body.display_name)
    except api_tokens.TokenError as exc:
        _fail(exc)


@router.patch("/api/admin/service-accounts/{account_id}", summary="Servis hesabının rolünü veya durumunu değiştir")
def update_account(account_id: str, body: AccountPatch, request: Request, user=Depends(admin)):
    try:
        api_tokens.update_account(settings_of(request), user["id"], account_id, role=body.role, active=body.active)
    except api_tokens.TokenError as exc:
        _fail(exc)
    return {"ok": True}


@router.post("/api/admin/service-accounts/{account_id}/tokens", status_code=201, summary="API anahtarı üret (bir kez gösterilir)")
def issue_token(account_id: str, body: TokenIn, request: Request, user=Depends(admin)):
    settings = settings_of(request)
    reauthenticate(settings, user, body.password)
    try:
        return api_tokens.issue(settings, user["id"], account_id, body.name, body.days)
    except api_tokens.TokenError as exc:
        _fail(exc)


@router.delete("/api/admin/tokens/{token_id}", summary="API anahtarını iptal et")
def revoke_token(token_id: str, request: Request, user=Depends(admin)):
    api_tokens.revoke(settings_of(request), user["id"], token_id)
    return {"ok": True}
