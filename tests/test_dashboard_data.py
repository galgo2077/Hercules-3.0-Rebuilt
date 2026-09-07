from __future__ import annotations

from Live.DashboardData import _display_trades, build_dashboard
from tests.test_endpoints import FakeSupabase


def test_display_trades_uses_positions_and_closing_fills_only() -> None:
    positions = [{"symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "0.01", "entryPrice": "100", "unRealizedProfit": "2", "updateTime": 2_000}]
    fills = [
        {"symbol": "BTCUSDT", "positionSide": "LONG", "side": "BUY", "qty": "0.01", "price": "100", "realizedPnl": "0", "time": 1_000},
        {"symbol": "ETHUSDT", "positionSide": "SHORT", "side": "BUY", "qty": "0.02", "price": "90", "realizedPnl": "3", "time": 3_000},
    ]

    trades = _display_trades(positions, fills)

    assert len(trades) == 2
    assert all(trade["source"] == "binance" for trade in trades)
    assert sum(trade["outcome"] == "open" for trade in trades) == 1
    assert sum(trade["exit_time"] is not None for trade in trades) == 1


def test_dashboard_never_falls_back_to_stored_trades(monkeypatch) -> None:
    database = FakeSupabase(
        {
            "exchange_accounts": [{"id": "a1", "user_id": "u1", "label": "test", "environment": "testnet"}],
            "trades": [{"account_id": "a1", "asset": "BTCUSDT", "outcome": "win"}],
            "live_positions": [],
            "equity_snapshots": [],
        }
    )
    monkeypatch.setattr("SharedParams.Supabase.get_service_client", lambda: database)
    monkeypatch.setattr("Live.DashboardData._exchange_snapshot", lambda accounts, assets: {"wallets": [], "positions": [], "trades": [], "errors": [{"error": "exchange unavailable"}]})

    dashboard = build_dashboard("u1", 10, ["BTCUSDT"])

    assert dashboard["trades"] == []
    assert dashboard["stats"]["fill_count"] == 0
