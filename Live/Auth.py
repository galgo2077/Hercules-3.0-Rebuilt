"""FastAPI dependency — validate Supabase JWT, extract user."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from SharedParams.Supabase import get_service_client

_bearer = HTTPBearer(auto_error=True)


@dataclass(frozen=True, slots=True)
class AuthUser:
    id: str
    email: str | None
    role: str  # "authenticated" | "service_role" | custom claim


async def _validate(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> AuthUser:
    """Validate Supabase access token via server-side get_user call."""
    try:
        client = get_service_client()
        resp = client.auth.get_user(creds.credentials)
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

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return AuthUser(id=str(user.id), email=user.email, role=user.role or "authenticated")


# FastAPI dependency — use in route as: user: Annotated[AuthUser, Depends(require_auth)]
require_auth = _validate
