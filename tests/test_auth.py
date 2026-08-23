from types import SimpleNamespace

from Live.Auth import _effective_role


def test_effective_role_uses_admin_app_metadata():
    user = SimpleNamespace(role="authenticated", app_metadata={"role": "admin"})

    assert _effective_role(user) == "admin"


def test_effective_role_rejects_unknown_metadata_role():
    user = SimpleNamespace(role="authenticated", app_metadata={"role": "service_role"})

    assert _effective_role(user) == "authenticated"
