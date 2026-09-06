"""FastAPI dependency — validate Supabase JWT, extract user."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from SharedParams.Supabase import get_service_client

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class AuthUser:
    id: str
    email: str | None
    role: str  # "authenticated" | "service_role" | custom claim


def _effective_role(user: object) -> str:
    """Return only server-assigned elevated roles from Supabase metadata."""
    app_metadata = getattr(user, "app_metadata", None)
    if isinstance(app_metadata, dict) and app_metadata.get("role") == "admin":
        return "admin"

    return "authenticated"


def _validate(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    access_token: Annotated[str | None, Cookie()] = None,
) -> AuthUser:
    """Validate Supabase access token via server-side get_user call."""
    token = creds.credentials if creds is not None else access_token
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        client = get_service_client()
        resp = client.auth.get_user(token)
        if resp is None:
            raise ValueError("empty authentication response")
        user = resp.user
        if user is None:
            raise ValueError("null user")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    return AuthUser(id=str(user.id), email=user.email, role=_effective_role(user))


# FastAPI dependency — use in route as: user: Annotated[AuthUser, Depends(require_auth)]
require_auth = _validate
