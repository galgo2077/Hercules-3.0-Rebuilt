"""Auth API — Supabase email/password login, logout, token refresh."""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field

from Live.Auth import AuthUser, require_auth

router = APIRouter(prefix="/api/auth", tags=["auth"])
_User = Annotated[AuthUser, Depends(require_auth)]
log = logging.getLogger(__name__)
_SECURITY = Path(__file__).resolve().parents[1] / "SharedData" / "Security.toml"


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=1024)


def _cookie(response: Response, name: str, value: str, max_age: int) -> None:
    with _SECURITY.open("rb") as handle:
        secure = bool(tomllib.load(handle).get("secure_cookie", False))
    response.set_cookie(name, value, max_age=max_age, httponly=True, secure=secure, samesite="strict", path="/")


@router.post("/login")
def login(body: LoginRequest, response: Response) -> dict:
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
    if session is None or user is None or not session.access_token or not session.refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login failed")
    _cookie(response, "access_token", session.access_token, int(session.expires_in or 3600))
    _cookie(response, "refresh_token", session.refresh_token, 60 * 60 * 24 * 30)
    return {"expires_in": session.expires_in, "user_id": str(user.id)}


@router.post("/logout")
def logout(
    user: _User,
    response: Response,
    access_token: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    from SharedParams.Supabase import get_service_client

    token = access_token
    if token is None and authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
    try:
        if token:
            get_service_client().auth.admin.sign_out(token)
    except Exception as exc:
        log.warning("Supabase sign-out failed: %s", exc)
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"status": "signed out"}


@router.post("/refresh")
def refresh(response: Response, refresh_token: Annotated[str | None, Cookie()] = None) -> dict:
    from SharedParams.Supabase import get_client

    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh token required")
    try:
        resp = get_client().auth.refresh_session(refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token") from exc

    session = resp.session
    if session is None or not session.access_token or not session.refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh failed")
    _cookie(response, "access_token", session.access_token, int(session.expires_in or 3600))
    _cookie(response, "refresh_token", session.refresh_token, 60 * 60 * 24 * 30)
    return {"expires_in": session.expires_in}
