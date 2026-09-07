"""Read-only dashboard aggregates for one authenticated user."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def _rows(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", [])
    return [dict(row) for row in data] if isinstance(data, list) else []


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _drawdown(values: Iterable[float]) -> float:
    peak = 0.0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = max(worst, peak - value)
    return worst


def _streaks(trades: list[dict[str, Any]]) -> tuple[int, int]:
    wins = losses = best_wins = best_losses = 0
    for trade in sorted(trades, key=lambda item: str(item.get("exit_time") or "")):
        if _number(trade.get("pnl")) > 0:
            wins, losses = wins + 1, 0
        elif _number(trade.get("pnl")) < 0:
            losses, wins = losses + 1, 0
        best_wins, best_losses = max(best_wins, wins), max(best_losses, losses)
    return best_wins, best_losses


def _timestamp(value: Any) -> str:
    return datetime.fromtimestamp(_number(value) / 1000, timezone.utc).isoformat()


def _display_trades(positions: list[dict[str, Any]], fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map Binance positions and closing fills to the dashboard trade shape."""
    active = [
        {
            "entry_time": _timestamp(position.get("updateTime")),
            "exit_time": None,
            "asset": position.get("symbol"),
            "side": position.get("positionSide"),
            "quantity": abs(_number(position.get("positionAmt"))),
            "entry_price": position.get("entryPrice"),
            "exit_price": None,
            "pnl": position.get("unRealizedProfit"),
            "outcome": "open",
            "source": "binance",
        }
        for position in positions
    ]
    closing = [
        fill
        for fill in fills
        if (fill.get("positionSide") == "LONG" and fill.get("side") == "SELL") or (fill.get("positionSide") == "SHORT" and fill.get("side") == "BUY")
    ]
    closed = [
        {
            "entry_time": _timestamp(fill.get("time")),
            "exit_time": _timestamp(fill.get("time")),
            "asset": fill.get("symbol"),
            "side": fill.get("positionSide"),
            "quantity": fill.get("qty"),
            "entry_price": None,
            "exit_price": fill.get("price"),
            "pnl": fill.get("realizedPnl"),
            "outcome": "win" if _number(fill.get("realizedPnl")) > 0 else "loss" if _number(fill.get("realizedPnl")) < 0 else "closed",
            "source": "binance",
        }
        for fill in closing
    ]
    return sorted([*active, *closed], key=lambda trade: str(trade["entry_time"]), reverse=True)


def _exchange_snapshot(accounts: list[dict[str, Any]], assets: list[str]) -> dict[str, Any]:
    """Read account state from Binance without placing or modifying anything."""
    import httpx

    from Live._client import BinanceClient
    from Live.Crypto import load_credential

    wallets: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for account in accounts:
        account_id = str(account["id"])
        if account.get("environment") == "paper":
            continue
        base_url = "https://fapi.binance.com" if account.get("environment") == "real" else "https://testnet.binancefuture.com"
        try:
            api_key, api_secret = load_credential(account_id)
            with BinanceClient(base_url, api_key=api_key, api_secret=api_secret) as client:
                balance = client.get("/fapi/v2/account")
                risk = client.get("/fapi/v2/positionRisk")
                active_positions = [row for row in risk if _number(row.get("positionAmt")) != 0] if isinstance(risk, list) else []
                for asset in sorted({*assets, *(str(row["symbol"]) for row in active_positions)}):
                    result = client.get("/fapi/v1/userTrades", symbol=asset, limit=1000)
                    if isinstance(result, list):
                        trades.extend(result)
            usdt = next((row for row in balance.get("assets", []) if row.get("asset") == "USDT"), {})
            wallets.append(usdt)
            if isinstance(risk, list):
                positions.extend(active_positions)
        except (httpx.HTTPError, KeyError, OSError, RuntimeError, TypeError, ValueError):
            log.warning("exchange snapshot failed for account %s", account_id)
            errors.append({"account_id": account_id, "error": "exchange unavailable"})
    return {"wallets": wallets, "positions": positions, "trades": trades, "errors": errors}


def build_dashboard(user_id: str, leverage: float, configured_assets: list[str], account_id: str | None = None) -> dict[str, Any]:
    """Return aggregate dashboard data scoped only to ``user_id``."""
    from SharedParams.Supabase import get_service_client

    db = get_service_client()
    all_accounts = _rows(db.table("exchange_accounts").select("id,label,environment").eq("user_id", user_id).execute())
    accounts = all_accounts
    if account_id:
        accounts = [account for account in accounts if str(account["id"]) == account_id]
    account_ids = [str(account["id"]) for account in accounts]
    positions: list[dict[str, Any]] = []
    equity: list[dict[str, Any]] = []
    for account_id in account_ids:
        positions.extend(_rows(db.table("live_positions").select("*").eq("account_id", account_id).execute()))
        equity.extend(_rows(db.table("equity_snapshots").select("*").eq("account_id", account_id).order("ts", desc=False).limit(500).execute()))

    assets = sorted({*configured_assets, *(str(row.get("asset")) for row in positions if row.get("asset"))})
    exchange = _exchange_snapshot(accounts, assets) if accounts else {"wallets": [], "positions": [], "trades": [], "errors": []}
    exchange_positions = exchange["positions"]
    exchange_trades = exchange["trades"]
    display_trades = _display_trades(exchange_positions, exchange_trades)
    closed = [trade for trade in display_trades if trade.get("exit_time")]
    pnls = [_number(trade.get("pnl")) for trade in closed]
    winners = [pnl for pnl in pnls if pnl > 0]
    losers = [pnl for pnl in pnls if pnl < 0]
    wallet = sum(_number(row.get("walletBalance")) for row in exchange["wallets"])
    available = sum(_number(row.get("availableBalance")) for row in exchange["wallets"])
    latest_equity = wallet if exchange["wallets"] else (_number(equity[-1].get("equity_usdt")) if equity else 0.0)
    open_size = sum(abs(_number(position.get("notional"))) for position in exchange_positions)
    unrealized = sum(_number(position.get("unRealizedProfit")) for position in exchange_positions)
    win_streak, loss_streak = _streaks(closed)
    gross_profit, gross_loss = sum(winners), abs(sum(losers))
    return {
        "accounts": all_accounts,
        "selected_account_id": account_id,
        "assets": assets,
        "trades": display_trades,
        "positions": exchange_positions or positions,
        "equity": equity,
        "exchange_errors": exchange.get("errors", []),
        "stats": {
            "equity_usdt": latest_equity,
            "available_usdt": available if exchange["wallets"] else latest_equity - open_size,
            "max_leverage": max((_number(position.get("leverage")) for position in exchange_positions), default=leverage),
            "max_drawdown_usdt": _drawdown(_number(row.get("equity_usdt")) for row in equity),
            "pnl_usdt": sum(pnls),
            "win_rate": len(winners) / len(closed) if closed else 0.0,
            "profit_factor": gross_profit / gross_loss if gross_loss else None,
            "longs": sum(1 for trade in closed if trade.get("side") == "LONG"),
            "shorts": sum(1 for trade in closed if trade.get("side") == "SHORT"),
            "gross_profit_usdt": gross_profit,
            "gross_loss_usdt": gross_loss,
            "expectancy_usdt": sum(pnls) / len(closed) if closed else 0.0,
            "best_trade_usdt": max(pnls, default=0.0),
            "worst_trade_usdt": min(pnls, default=0.0),
            "consecutive_wins": win_streak,
            "consecutive_losses": loss_streak,
            "unrealized_pnl_usdt": unrealized,
            "fill_count": len(exchange_trades) if accounts and not exchange["errors"] else 0,
            "position_size": open_size,
            "funding_rate": None,
            "open_mismatches": 0,
        },
    }
