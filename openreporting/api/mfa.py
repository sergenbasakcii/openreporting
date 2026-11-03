"""Own-account MFA only; factor changes require primary reauthentication and CSRF."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg import Error as PostgresError
from pydantic import BaseModel, Field

from .. import mfa
from ..security import authenticate
from ..secrets_store import SecretError
from .deps import settings_of, viewer_write

router = APIRouter()


def ensure_transport(request):
    # Behind the bundled nginx the scheme comes from X-Forwarded-Proto. A loopback client is only
    # exempt on local HTTP setups; otherwise a proxy that drops the header would look like localhost.
    local_http = not settings_of(request).secure_cookie and request.client and request.client.host in {"127.0.0.1", "::1"}
    if request.scope["scheme"] != "https" and not local_http:
        raise HTTPException(400, "HTTPS is required for second-factor operations")


class Primary(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class Proof(Primary):
    code: str = Field(min_length=1, max_length=128)


class Confirm(Proof):
    setup_token: str = Field(min_length=1, max_length=128)


def run(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except (mfa.Unavailable, SecretError, sqlite3.Error, PostgresError, OSError):
        raise HTTPException(503, "Second-factor storage unavailable") from None


@router.get("/api/user/mfa")
def status(request: Request, user=Depends(authenticate)):
    return run(mfa.status, settings_of(request), user)


@router.post("/api/user/mfa/setup")
def setup(body: Primary, request: Request, user=Depends(viewer_write)):
    ensure_transport(request)
    return run(mfa.start_setup, settings_of(request), user, body.password)


@router.post("/api/user/mfa/confirm")
def confirm(body: Confirm, request: Request, user=Depends(viewer_write)):
    ensure_transport(request)
    return run(mfa.confirm_setup, settings_of(request), user, body.password, body.code, body.setup_token)


@router.post("/api/user/mfa/disable")
def disable(body: Proof, request: Request, user=Depends(viewer_write)):
    ensure_transport(request)
    return run(mfa.manage, settings_of(request), user, body.password, body.code, disable=True)


@router.post("/api/user/mfa/recovery")
def recovery(body: Proof, request: Request, user=Depends(viewer_write)):
    ensure_transport(request)
    return run(mfa.manage, settings_of(request), user, body.password, body.code)
