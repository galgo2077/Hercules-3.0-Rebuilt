"""Risk gate: drawdown halt, kill switch, short cap, size calculation."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from Live.Risk import (
    RiskState,
    check_entry,
    kill_active,
    on_entry,
    on_exit,
    size_trade,
    update_equity,
)


def _state(**kw) -> RiskState:
    return RiskState(initial_equity=100.0, current_equity=100.0, **kw)


def test_entry_allowed():
    ok, reason = check_entry(_state(), "LONG", "BTCUSDT", 15.0)
    assert ok
    assert reason == ""


def test_drawdown_blocks():
    s = RiskState(initial_equity=100.0, current_equity=75.0, max_drawdown_pct=0.20)
    ok, reason = check_entry(s, "LONG", "BTCUSDT", 10.0)
    assert not ok
    assert "drawdown" in reason
    assert s.blocked


def test_blocked_state_stays_blocked():
    s = _state()
    s.blocked = True
    s.block_reason = "manual"
    ok, _ = check_entry(s, "SHORT", "ETHUSDT", 5.0)
    assert not ok


def test_short_cap():
    s = RiskState(initial_equity=100.0, current_equity=100.0, max_concurrent_shorts=2)
    s.open_shorts = 2
    ok, reason = check_entry(s, "SHORT", "SOLUSDT", 10.0)
    assert not ok
    assert "short" in reason.lower()


def test_long_not_blocked_by_short_cap():
    s = RiskState(initial_equity=100.0, current_equity=100.0, max_concurrent_shorts=2)
    s.open_shorts = 2
    ok, _ = check_entry(s, "LONG", "BTCUSDT", 10.0)
    assert ok


def test_amount_too_small():
    ok, reason = check_entry(_state(), "LONG", "BTCUSDT", 0.5)
    assert not ok


def test_on_entry_increments_shorts():
    s = _state()
    on_entry(s, "SHORT")
    assert s.open_shorts == 1
    on_entry(s, "LONG")
    assert s.open_shorts == 1


def test_on_exit_decrements_shorts():
    s = _state()
    s.open_shorts = 3
    on_exit(s, "SHORT")
    assert s.open_shorts == 2
    on_exit(s, "LONG")
    assert s.open_shorts == 2


def test_update_equity():
    s = _state()
    update_equity(s, 120.0)
    assert s.current_equity == 120.0


def test_kill_switch_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr("Live.Risk._KILL", tmp_path / "kill.json")
    assert not kill_active()


def test_kill_switch_active(tmp_path, monkeypatch):
    kf = tmp_path / "kill.json"
    kf.write_text(json.dumps({"active": True}))
    monkeypatch.setattr("Live.Risk._KILL", kf)
    s = _state()
    ok, reason = check_entry(s, "LONG", "BTCUSDT", 10.0)
    assert not ok
    assert "kill" in reason
