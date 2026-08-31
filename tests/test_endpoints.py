"""FastAPI endpoint tests — mocked Supabase and filesystem, no real network."""

from __future__ import annotations

import json
import asyncio
from datetime import datetime, timezone

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

def test_dashboard_returns_snapshot(client_user, monkeypatch):
    monkeypatch.setattr("SharedParams.Supabase.get_service_client", lambda: FakeSupabase([]))
    monkeypatch.setattr("Live.Readiness.build", lambda assets: [])
    r = client_user.get("/api/dashboard")
    assert r.status_code == 200
    assert "stats" in r.json()


def test_readiness_marks_signal_without_entry_as_yellow(monkeypatch):
    import polars as pl
    import Live.Readiness as readiness

    readiness._CACHE = (0, [])
    decisions = pl.DataFrame({
        "asset": ["BTCUSDT"], "final_signal": [1], "action": ["Hold"],
        "entry_allowed": [False], "reason": ["slope_not_confirmed"],
        "timestamp": [datetime(2026, 8, 25, tzinfo=timezone.utc)],
    })
    monkeypatch.setattr("Dataframe.OhlcvCache.fetch_warmup", lambda *args: pl.DataFrame())
    monkeypatch.setattr("Dataframe.Frame.build", lambda *args: pl.DataFrame())
    monkeypatch.setattr("Strategy.Strategy.evaluate", lambda *args: decisions)
    result = readiness.build(["BTCUSDT"])
    assert result[0]["state"] == "yellow"


def test_demo_dispatches_closed_candles_for_every_configured_asset(monkeypatch):
    from Live.Demo import DemoEngine

    engine = DemoEngine()
    dispatched: list[str] = []

    async def record(_client, asset):
        dispatched.append(asset)

    monkeypatch.setattr(engine._buffer, "ingest_ws", lambda *_args: True)
    monkeypatch.setattr(engine._buffer, "ready", lambda *_args: True)
    monkeypatch.setattr(engine, "_process_asset", record)

    async def dispatch_all():
        for asset in engine._assets:
            msg = {"stream": f"{asset.lower()}@kline_1h", "data": {"k": {"t": 123, "x": True}}}
            engine._dispatch_candle(object(), msg)
            engine._dispatch_candle(object(), msg)
        await asyncio.sleep(0)

    asyncio.run(dispatch_all())
    assert dispatched == engine._assets


def test_binance_quantity_uses_each_asset_exchange_filters(monkeypatch):
    from Live import _client

    _client._symbol_filters.clear()
    filters = {
        "BTCUSDT": ("0.001", "0.001", "5"),
        "ETHUSDT": ("0.001", "0.001", "5"),
        "SOLUSDT": ("0.1", "0.1", "5"),
        "XRPUSDT": ("1", "1", "5"),
    }

    class FakeHttp:
        def get(self, _url, params=None):
            symbol = params["symbol"]
            step, minimum, notional = filters[symbol]
            return type("Response", (), {"is_error": False, "json": lambda self: {"symbols": [{
                "symbol": symbol,
                "filters": [
                    {"filterType": "LOT_SIZE", "stepSize": step, "minQty": minimum},
                    {"filterType": "MIN_NOTIONAL", "minNotional": notional},
                ],
            }]}})()

    client = _client.BinanceClient.__new__(_client.BinanceClient)
    client._base = "https://test.invalid"
    client._http = FakeHttp()
    for symbol in filters:
        assert float(client.quantity(symbol, 100.0, 10.0)) >= float(filters[symbol][1])


def test_position_tracker_clears_position_missing_from_exchange():
    from Live.Positions import PositionTracker

    class Client:
        def __init__(self):
            self.raw = [{"symbol": "BTCUSDT", "positionAmt": "0.01", "markPrice": "100", "entryPrice": "90", "unRealizedProfit": "0"}]
        def get(self, _path):
            return self.raw

    client = Client()
    tracker = PositionTracker()
    tracker.fetch(client)
    assert tracker.get("BTCUSDT").side == "LONG"
    client.raw = []
    tracker.fetch(client)
    assert tracker.get("BTCUSDT").is_flat


def test_status_ok(client_user):
    r = client_user.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["is_admin"] is False


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
    monkeypatch.setattr("SharedParams.Supabase.get_service_client", lambda: FakeSupabase(fake_data))
    r = client_user.get("/api/trades")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_trades_empty(client_user, monkeypatch):
    monkeypatch.setattr("SharedParams.Supabase.get_service_client", lambda: FakeSupabase([]))
    r = client_user.get("/api/trades")
    assert r.status_code == 200
    assert r.json() == []


def test_delete_trade_204(client_user, monkeypatch):
    monkeypatch.setattr("SharedParams.Supabase.get_service_client", lambda: FakeSupabase())
    r = client_user.delete("/api/trades/1")
    assert r.status_code == 204


# ── Positions ─────────────────────────────────────────────────────────────────

def test_positions_returns_list(client_user, monkeypatch):
    monkeypatch.setattr("SharedParams.Supabase.get_service_client",
                        lambda: FakeSupabase([{"asset": "BTCUSDT", "side": "LONG"}]))
    r = client_user.get("/api/positions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_manual_close_user_forbidden(client_user):
    r = client_user.post("/api/positions/close", json={"account_id": "a1", "symbol": "BTCUSDT", "position_side": "LONG"})
    assert r.status_code == 403


def test_manual_close_admin_rechecks_and_closes(client_admin, monkeypatch):
    client, _ = client_admin
    calls = []

    class FakeBinanceClient:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, path):
            assert path == "/fapi/v2/positionRisk"
            return [{"symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "0.0010"}]
        def post(self, path, **params):
            calls.append((path, params))
            return {"orderId": 123}

    monkeypatch.setattr("SharedParams.Supabase.get_service_client", lambda: FakeSupabase([{"id": "a1", "user_id": "admin1", "environment": "testnet"}]))
    monkeypatch.setattr("Live.Crypto.load_credential", lambda account_id: ("key", "secret"))
    monkeypatch.setattr("Live._client.BinanceClient", FakeBinanceClient)
    r = client.post("/api/positions/close", json={"account_id": "a1", "symbol": "BTCUSDT", "position_side": "LONG"})
    assert r.status_code == 200
    assert r.json()["status"] == "closed"
    assert calls == [("/fapi/v1/order", {"symbol": "BTCUSDT", "side": "SELL", "type": "MARKET", "positionSide": "LONG", "quantity": "0.0010"})]


# ── Equity ────────────────────────────────────────────────────────────────────

def test_equity_returns_list(client_user, monkeypatch):
    monkeypatch.setattr("SharedParams.Supabase.get_service_client",
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
