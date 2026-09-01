import tempfile
from unittest.mock import patch

from major_tom.audit import _expected_error, audit
from major_tom.watchdog import watchdog


def test_expected_user_errors_are_ignored():
    assert _expected_error("insufficient funds")
    assert _expected_error("invalid input")
    assert not _expected_error("signal sent, trade not executed")

@patch("major_tom.audit._git_state", return_value={"sha": "abc", "clean": True, "error": None})
@patch("major_tom.audit._health", return_value={"ok": True, "status": 200, "latency_ms": 1})
@patch("major_tom.audit._service_state", return_value={"active": True, "output": "active"})
def test_audit_healthy(_service, _health_check, _git):
    result = audit({"repo": "."})
    assert result["ok"] and result["severity"] == "INFO"

@patch("major_tom.watchdog._service_state", return_value={"active": True, "output": "active"})
@patch("major_tom.watchdog._health", return_value={"ok": True})
@patch("major_tom.watchdog.bridge_health", return_value={"healthy": True})
def test_watchdog_requires_fresh_audit_and_db(_bridge, _health_check, _service):
    with tempfile.NamedTemporaryFile() as marker:
        result = watchdog({"audit_file": marker.name, "db_health_url": "https://db/health"})
    assert result["ok"]
