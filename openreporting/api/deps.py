"""Shared FastAPI dependencies: authentication, CSRF and role gates."""
from fastapi import Depends, HTTPException, Request

from ..runtime_settings import effective
from ..security import authenticate, require_csrf, require_role


def settings_of(request: Request):
    # Environment settings plus admin-UI overrides (re-read when they change).
    return effective(request.app.state.settings)


def viewer_write(request: Request, user=Depends(authenticate)):
    """Any signed-in user performing a CSRF-protected POST (e.g. running queries)."""
    require_csrf(request, user)
    return user


def editor(request: Request, user=Depends(authenticate)):
    require_csrf(request, user)
    require_role(user, "admin", "editor")
    return user


def admin(request: Request, user=Depends(authenticate)):
    require_csrf(request, user)
    require_role(user, "admin")
    return user


def admin_read(user=Depends(authenticate)):
    require_role(user, "admin")
    return user


def domain_errors(exc):
    raise HTTPException(422, str(exc)) from exc
