from __future__ import annotations

import json
import logging

from Live.Notifications import _MajorTomHandler, notify


def test_trade_warning_and_error_notifications_are_sanitized(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MAJOR_TOM_OUTBOX_DIR", str(tmp_path))
    notify("TRADE", "TESTNET ENTRY LONG BTCUSDT")
    handler = _MajorTomHandler(logging.WARNING)
    handler.emit(logging.LogRecord("hercules", logging.WARNING, "", 0, "retry signature=secret-value", (), None))
    handler.emit(logging.LogRecord("hercules", logging.ERROR, "", 0, "worker failed", (), None))

    messages = [json.loads(path.read_text()) for path in sorted(tmp_path.glob("*.json"))]
    assert [message["kind"] for message in messages] == ["TRADE", "WARNING", "ERROR"]
    assert "secret-value" not in messages[1]["message"]
    assert "signature=<redacted>" in messages[1]["message"]
