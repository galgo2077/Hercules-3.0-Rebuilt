from __future__ import annotations

from Live.DashboardData import _display_trades, build_dashboard
from tests.test_endpoints import FakeSupabase


def test_display_trades_uses_positions_and_closing_fills_only() -> None:
    positions = [{"symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "0.01", "entryPrice": "100", "markPrice": "101", "liquidationPrice": "80", "leverage": "5", "unRealizedProfit": "2", "updateTime": 2_000}]
    fills = [
        {"symbol": "BTCUSDT", "positionSide": "LONG", "side": "BUY", "qty": "0.01", "price": "100", "realizedPnl": "0", "time": 1_000},
        {"symbol": "ETHUSDT", "positionSide": "SHORT", "side": "BUY", "qty": "0.02", "price": "90", "realizedPnl": "3", "time": 3_000},
    ]

    orders = [
        {"symbol": "BTCUSDT", "positionSide": "LONG", "orderType": "STOP_MARKET", "triggerPrice": "94"},
        {"symbol": "BTCUSDT", "positionSide": "LONG", "orderType": "TAKE_PROFIT_MARKET", "triggerPrice": "103"},
    ]
    trades = _display_trades(positions, fills, orders)

    assert len(trades) == 2
    assert all(trade["source"] == "binance" for trade in trades)
    assert sum(trade["outcome"] == "open" for trade in trades) == 1
    assert sum(trade["exit_time"] is not None for trade in trades) == 1
    active = next(trade for trade in trades if trade["outcome"] == "open")
    assert (active["trend"], active["stop_loss"], active["take_profit"]) == ("BULLISH", "94", "103")


def test_display_trades_reconstructs_real_fill_cycle() -> None:
    fills = [
        {"symbol": "BTCUSDT", "positionSide": "LONG", "side": "BUY", "qty": "0.01", "price": "100", "realizedPnl": "0", "time": 1_000},
        {"symbol": "BTCUSDT", "positionSide": "LONG", "side": "SELL", "qty": "0.01", "price": "110", "realizedPnl": "1", "time": 2_000},
    ]

    trades = _display_trades([], fills)

    assert len(trades) == 1
    assert trades[0]["entry_time"] != trades[0]["exit_time"]
    assert (trades[0]["entry_price"], trades[0]["exit_price"], trades[0]["pnl"]) == (100, 110, 1)


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
    monkeypatch.setattr("Live.DashboardData._exchange_snapshot", lambda accounts, assets: {"wallets": [], "positions": [], "trades": [], "protection_orders": [], "errors": [{"error": "exchange unavailable"}]})

    dashboard = build_dashboard("u1", 10, ["BTCUSDT"])

    assert dashboard["trades"] == []
    assert dashboard["stats"]["fill_count"] == 0


def test_dashboard_defaults_to_one_visible_account(monkeypatch) -> None:
    database = FakeSupabase(
        {
            "exchange_accounts": [
                {"id": "a1", "user_id": "u1", "label": "test", "environment": "testnet"},
                {"id": "a2", "user_id": "u1", "label": "other", "environment": "testnet"},
            ],
            "live_positions": [],
            "equity_snapshots": [],
        }
    )
    selected = []
    monkeypatch.setattr("SharedParams.Supabase.get_service_client", lambda: database)
    monkeypatch.setattr(
        "Live.DashboardData._exchange_snapshot",
        lambda accounts, assets: selected.extend(accounts) or {"wallets": [], "positions": [], "trades": [], "protection_orders": [], "errors": []},
    )

    dashboard = build_dashboard("u1", 10, ["BTCUSDT"])

    assert dashboard["selected_account_id"] == "a1"
    assert [account["id"] for account in selected] == ["a1"]
