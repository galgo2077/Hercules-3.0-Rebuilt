"""Read-only dashboard aggregates for one authenticated user."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


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
        base_url = "https://fapi.binance.com" if account.get("environment") == "real" else "https://testnet.binancefuture.com"
        try:
            api_key, api_secret = load_credential(account_id)
            with BinanceClient(base_url, api_key=api_key, api_secret=api_secret) as client:
                balance = client.get("/fapi/v2/account")
                risk = client.get("/fapi/v2/positionRisk")
                for asset in assets:
                    result = client.get("/fapi/v1/userTrades", symbol=asset, limit=100)
                    if isinstance(result, list):
                        trades.extend(result)
            usdt = next((row for row in balance.get("assets", []) if row.get("asset") == "USDT"), {})
            wallets.append(usdt)
            if isinstance(risk, list):
                positions.extend(row for row in risk if _number(row.get("positionAmt")) != 0)
        except (httpx.HTTPError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            errors.append({"account_id": account_id, "error": str(exc)[:160]})
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
    trades: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    equity: list[dict[str, Any]] = []
    for account_id in account_ids:
        trades.extend(_rows(db.table("trades").select("*").eq("account_id", account_id).order("entry_time", desc=True).limit(500).execute()))
        positions.extend(_rows(db.table("live_positions").select("*").eq("account_id", account_id).execute()))
        equity.extend(_rows(db.table("equity_snapshots").select("*").eq("account_id", account_id).order("ts", desc=False).limit(500).execute()))

    assets = sorted({*configured_assets, *(str(row.get("asset")) for row in [*trades, *positions] if row.get("asset"))})
    exchange = _exchange_snapshot(accounts, assets) if accounts else {"wallets": [], "positions": [], "trades": [], "errors": []}
    exchange_positions = exchange["positions"]
    exchange_trades = exchange["trades"]
    closed = [trade for trade in trades if trade.get("exit_time")]
    pnls = [_number(trade.get("pnl")) for trade in closed]
    winners = [pnl for pnl in pnls if pnl > 0]
    losers = [pnl for pnl in pnls if pnl < 0]
    wallet = sum(_number(row.get("walletBalance")) for row in exchange["wallets"])
    available = sum(_number(row.get("availableBalance")) for row in exchange["wallets"])
    latest_equity = wallet or (_number(equity[-1].get("equity_usdt")) if equity else 0.0)
    open_size = sum(abs(_number(position.get("notional"))) for position in exchange_positions)
    unrealized = sum(_number(position.get("unRealizedProfit")) for position in exchange_positions)
    exchange_pnls = [_number(trade.get("realizedPnl")) for trade in exchange_trades]
    exchange_winners = [pnl for pnl in exchange_pnls if pnl > 0]
    exchange_losers = [pnl for pnl in exchange_pnls if pnl < 0]
    display_trades = [
        {
            "entry_time": trade.get("time"), "asset": trade.get("symbol"), "side": trade.get("side"),
            "quantity": trade.get("qty"), "entry_price": trade.get("price"), "exit_price": None,
            "pnl": trade.get("realizedPnl"), "outcome": "win" if _number(trade.get("realizedPnl")) > 0 else "open",
        } for trade in exchange_trades
    ] or trades[:100]
    win_streak, loss_streak = _streaks(closed)
    gross_profit, gross_loss = sum(winners), abs(sum(losers))
    from Live.Readiness import build as build_readiness

    return {
        "accounts": all_accounts,
        "selected_account_id": account_id,
        "assets": assets,
        "trades": display_trades,
        "positions": exchange_positions or positions,
        "equity": equity,
        "exchange_errors": exchange.get("errors", []),
        "readiness": build_readiness(assets),
        "stats": {
            "equity_usdt": latest_equity,
            "available_usdt": available or latest_equity - open_size,
            "max_leverage": max((_number(position.get("leverage")) for position in exchange_positions), default=leverage),
            "max_drawdown_usdt": _drawdown(_number(row.get("equity_usdt")) for row in equity),
            "pnl_usdt": sum(exchange_pnls) or sum(pnls),
            "win_rate": len(exchange_winners) / len(exchange_pnls) if exchange_pnls else (len(winners) / len(closed) if closed else 0.0),
            "profit_factor": (sum(exchange_winners) / abs(sum(exchange_losers)) if exchange_losers else None) or (gross_profit / gross_loss if gross_loss else None),
            "longs": sum(1 for trade in exchange_trades if trade.get("side") == "BUY") or sum(1 for trade in trades if trade.get("side") == "LONG"),
            "shorts": sum(1 for trade in exchange_trades if trade.get("side") == "SELL") or sum(1 for trade in trades if trade.get("side") == "SHORT"),
            "gross_profit_usdt": sum(exchange_winners) or gross_profit,
            "gross_loss_usdt": abs(sum(exchange_losers)) or gross_loss,
            "expectancy_usdt": (sum(exchange_pnls) / len(exchange_pnls)) if exchange_pnls else (sum(pnls) / len(closed) if closed else 0.0),
            "best_trade_usdt": max(pnls, default=0.0),
            "worst_trade_usdt": min(pnls, default=0.0),
            "consecutive_wins": win_streak,
            "consecutive_losses": loss_streak,
            "unrealized_pnl_usdt": unrealized,
            "fill_count": len(exchange_trades) or len(trades),
            "position_size": open_size,
            "funding_rate": None,
            "open_mismatches": 0,
        },
    }
