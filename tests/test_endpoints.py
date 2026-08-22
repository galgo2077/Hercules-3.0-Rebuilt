"""FastAPI endpoint tests — mocked Supabase and filesystem, no real network."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


# ── Fake Supabase chain ───────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, data):
        self.data = data

class _FakeQuery:
    def __init__(self, data):
        self._data = data
    def select(self, *a, **kw): return self
    def order(self, *a, **kw): return self
    def limit(self, *a, **kw): return self
    def eq(self, *a, **kw): return self
    def delete(self): return self
    def execute(self): return _FakeResp(self._data)

class FakeSupabase:
    def __init__(self, data=None):
        self._data = data or []
    def table(self, name: str): return _FakeQuery(self._data)


# ── App + auth fixture ────────────────────────────────────────────────────────

def _strip_static_mount(app):
    """Remove StaticFiles mount at '/' so API routes are reachable in tests."""
    from starlette.routing import Mount
    from starlette.staticfiles import StaticFiles
    kept = [r for r in app.routes if not (isinstance(r, Mount) and isinstance(getattr(r, "app", None), StaticFiles))]
    app.routes[:] = kept


@pytest.fixture()
def client_user(monkeypatch, tmp_path):
    from Live.Server import app
    from Live.Auth import require_auth, AuthUser
    _strip_static_mount(app)
    user = AuthUser(id="u1", email=None, role="user")
    app.dependency_overrides[require_auth] = lambda: user
    # point kill switch to tmp dir so no filesystem side effects
    monkeypatch.setattr("Live.Server._KILL_SWITCH", tmp_path / "kill.json")
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def client_admin(monkeypatch, tmp_path):
    from Live.Server import app
    from Live.Auth import require_auth, AuthUser
    _strip_static_mount(app)
    user = AuthUser(id="admin1", email=None, role="admin")
    app.dependency_overrides[require_auth] = lambda: user
    monkeypatch.setattr("Live.Server._KILL_SWITCH", tmp_path / "kill.json")
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=True) as c:
        yield c, tmp_path
    app.dependency_overrides.clear()


# ── Status ────────────────────────────────────────────────────────────────────

def test_status_ok(client_user):
    r = client_user.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True


def test_status_kill_switch_inactive(client_user):
    r = client_user.get("/api/status")
    assert r.json()["kill_switch"] is False


# ── Kill switch ───────────────────────────────────────────────────────────────

def test_kill_status_inactive(client_user):
    r = client_user.get("/api/kill")
    assert r.status_code == 200
    assert r.json() == {"active": False}


def test_kill_activate_admin(client_admin):
    c, tmp_path = client_admin
    r = c.post("/api/kill/activate")
    assert r.status_code == 200
    assert r.json()["status"] == "activated"
    kill_file = tmp_path / "kill.json"
    assert kill_file.exists()
    assert json.loads(kill_file.read_text())["active"] is True


def test_kill_activate_user_forbidden(client_user):
    r = client_user.post("/api/kill/activate")
    assert r.status_code == 403


def test_kill_reset_admin(client_admin):
    c, tmp_path = client_admin
    # activate first
    c.post("/api/kill/activate")
    r = c.post("/api/kill/reset")
    assert r.status_code == 200
    assert r.json()["status"] == "reset"
    kill_file = tmp_path / "kill.json"
    assert json.loads(kill_file.read_text())["active"] is False


def test_kill_active_shows_in_status(client_admin):
    c, tmp_path = client_admin
    c.post("/api/kill/activate")
    r = c.get("/api/status")
    assert r.json()["kill_switch"] is True


# ── Trades ────────────────────────────────────────────────────────────────────

def test_trades_returns_list(client_user, monkeypatch):
    fake_data = [{"id": 1, "asset": "BTCUSDT", "side": "long"}]
    monkeypatch.setattr("SharedParams.Supabase.get_client", lambda: FakeSupabase(fake_data))
    r = client_user.get("/api/trades")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_trades_empty(client_user, monkeypatch):
    monkeypatch.setattr("SharedParams.Supabase.get_client", lambda: FakeSupabase([]))
    r = client_user.get("/api/trades")
    assert r.status_code == 200
    assert r.json() == []


def test_delete_trade_204(client_user, monkeypatch):
    monkeypatch.setattr("SharedParams.Supabase.get_service_client", lambda: FakeSupabase())
    r = client_user.delete("/api/trades/1")
    assert r.status_code == 204


# ── Positions ─────────────────────────────────────────────────────────────────

def test_positions_returns_list(client_user, monkeypatch):
    monkeypatch.setattr("SharedParams.Supabase.get_client",
                        lambda: FakeSupabase([{"asset": "BTCUSDT", "side": "LONG"}]))
    r = client_user.get("/api/positions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── Equity ────────────────────────────────────────────────────────────────────

def test_equity_returns_list(client_user, monkeypatch):
    monkeypatch.setattr("SharedParams.Supabase.get_client",
                        lambda: FakeSupabase([{"ts": "2024-01-01T00:00:00", "equity": 10000.0}]))
    r = client_user.get("/api/equity")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── Candles ───────────────────────────────────────────────────────────────────

def test_candles_returns_list(client_user, monkeypatch):
    import datetime
    import polars as pl
    fake_df = pl.DataFrame({
        "timestamp": [datetime.datetime(2024, 1, 1)],
        "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5],
        "volume": [1000.0], "asset": ["BTCUSDT"],
    })
    monkeypatch.setattr("Dataframe.Binance.fetch_historical", lambda *a, **kw: fake_df)
    r = client_user.get("/api/candles?asset=BTCUSDT&limit=10")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1


# ── Config ────────────────────────────────────────────────────────────────────

def test_config_returns_keys(client_user, monkeypatch):
    from SharedParams.Config import (
        HerculesConfig, PortfolioConfig, DataframeConfig, BacktestConfig, ServerConfig
    )
    fake_cfg = HerculesConfig(
        portfolio=PortfolioConfig(
            weights={"BTCUSDT": 1.0}, leverage=8.0, trade_size_pct=0.15,
            take_profit_pct=0.03, checkpoint_trail_pct=0.008,
            short_trailing_stop_pct=0.018, stop_loss_pct=0.06,
            short_exit_on_bullish_trend=True, max_concurrent_shorts=5,
        ),
        dataframe=DataframeConfig(interval="1h", warmup_bars=200),
        backtest=BacktestConfig(
            start_date="2024-01-01", end_date="2024-12-31",
            assets=["BTCUSDT"], initial_cash=10000.0,
            minimum_free_equity=10.0, max_gross_exposure=1.0,
            allow_short=True, fee_rate=0.0004, slippage_rate=0.0001,
        ),
        server=ServerConfig(host="127.0.0.1", port=8765, mode="paper"),
    )
    monkeypatch.setattr("SharedParams.Config.load", lambda: fake_cfg)
    r = client_user.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert "portfolio" in body
    assert "backtest" in body
    assert "server" in body
