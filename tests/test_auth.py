from types import SimpleNamespace

import pytest
from fastapi import Response

from Live.Auth import _effective_role


def test_effective_role_uses_admin_app_metadata():
    user = SimpleNamespace(role="authenticated", app_metadata={"role": "admin"})

    assert _effective_role(user) == "admin"


def test_effective_role_rejects_unknown_metadata_role():
    user = SimpleNamespace(role="authenticated", app_metadata={"role": "service_role"})

    assert _effective_role(user) == "authenticated"


def test_login_tokens_only_use_http_only_cookies(monkeypatch) -> None:
    from Live.AuthRouter import LoginRequest, login

    session = SimpleNamespace(access_token="access-secret", refresh_token="refresh-secret", expires_in=3600)
    auth = SimpleNamespace(sign_in_with_password=lambda credentials: SimpleNamespace(session=session, user=SimpleNamespace(id="u1")))
    monkeypatch.setattr("SharedParams.Supabase.get_client", lambda: SimpleNamespace(auth=auth))
    response = Response()
    body = login(LoginRequest(email="user@example.com", password="password1"), response)
    cookies = response.headers.getlist("set-cookie")
    assert body == {"expires_in": 3600, "user_id": "u1"}
    assert len(cookies) == 2
    assert all("HttpOnly" in cookie and "SameSite=strict" in cookie for cookie in cookies)
    assert "access-secret" not in str(body)
    assert "refresh-secret" not in str(body)


def test_logout_revokes_presented_access_token(monkeypatch) -> None:
    from Live.Auth import AuthUser
    from Live.AuthRouter import logout

    revoked = []
    admin = SimpleNamespace(sign_out=lambda token: revoked.append(token))
    monkeypatch.setattr("SharedParams.Supabase.get_service_client", lambda: SimpleNamespace(auth=SimpleNamespace(admin=admin)))
    response = Response()
    assert logout(AuthUser("u1", None, "authenticated"), response, access_token="access-secret") == {"status": "signed out"}
    assert revoked == ["access-secret"]


def test_login_rejects_session_without_refresh_token(monkeypatch) -> None:
    from fastapi import HTTPException

    from Live.AuthRouter import LoginRequest, login

    session = SimpleNamespace(access_token="access-secret", refresh_token=None, expires_in=3600)
    auth = SimpleNamespace(sign_in_with_password=lambda credentials: SimpleNamespace(session=session, user=SimpleNamespace(id="u1")))
    monkeypatch.setattr("SharedParams.Supabase.get_client", lambda: SimpleNamespace(auth=auth))
    with pytest.raises(HTTPException, match="401"):
        login(LoginRequest(email="user@example.com", password="password1"), Response())
