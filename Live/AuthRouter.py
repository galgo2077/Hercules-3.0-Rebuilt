"""Auth API — Supabase email/password login, logout, token refresh."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from Live.Auth import AuthUser, require_auth

router = APIRouter(prefix="/api/auth", tags=["auth"])
_User = Annotated[AuthUser, Depends(require_auth)]
log = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/login")
async def login(body: LoginRequest) -> dict:
    from SharedParams.Supabase import get_client

    try:
        resp = get_client().auth.sign_in_with_password(
            {
                "email": body.email,
                "password": body.password,
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials") from exc

    session = resp.session
    user = resp.user
    if session is None or user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login failed")
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_in": session.expires_in,
        "user_id": str(user.id),
    }


@router.post("/logout")
async def logout(user: _User) -> dict:
    from SharedParams.Supabase import get_client

    try:
        get_client().auth.sign_out()
    except Exception as exc:
        log.warning("Supabase sign-out failed: %s", exc)
    return {"status": "signed out"}


@router.post("/refresh")
async def refresh(body: RefreshRequest) -> dict:
    from SharedParams.Supabase import get_client

    try:
        resp = get_client().auth.refresh_session(body.refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token") from exc

    session = resp.session
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh failed")
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_in": session.expires_in,
    }
