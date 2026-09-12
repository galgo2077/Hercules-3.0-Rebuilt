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


def _source(row: dict[str, Any]) -> str:
    environment = row.get("_environment")
    return f"binance-{environment}" if environment else "binance"


def _closed_fill_cycles(fills: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[tuple[Any, Any, Any], dict[str, Any]]]:
    """Reconstruct completed position cycles from exchange-confirmed fills."""
    closed: list[dict[str, Any]] = []
    open_cycles: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for fill in sorted(fills, key=lambda row: _number(row.get("time"))):
        side = fill.get("positionSide")
        order_side = fill.get("side")
        if side not in {"LONG", "SHORT"}:
            continue
        key = (fill.get("_account_id"), fill.get("symbol"), side)
        is_entry = (side == "LONG" and order_side == "BUY") or (side == "SHORT" and order_side == "SELL")
        is_exit = (side == "LONG" and order_side == "SELL") or (side == "SHORT" and order_side == "BUY")
        quantity, price = _number(fill.get("qty")), _number(fill.get("price"))
        if is_entry and quantity > 0:
            cycle = open_cycles.setdefault(
                key,
                {"entry_time": _timestamp(fill.get("time")), "open_qty": 0.0, "entry_qty": 0.0, "entry_value": 0.0, "closed_qty": 0.0, "exit_value": 0.0, "pnl": 0.0, "row": fill},
            )
            cycle["open_qty"] += quantity
            cycle["entry_qty"] += quantity
            cycle["entry_value"] += quantity * price
        elif is_exit and quantity > 0:
            cycle = open_cycles.get(key)
            if not cycle:
                pnl = _number(fill.get("realizedPnl"))
                closed.append(
                    {
                        "entry_time": None,
                        "exit_time": _timestamp(fill.get("time")),
                        "asset": fill.get("symbol"),
                        "side": side,
                        "trend": "BULLISH" if side == "LONG" else "BEARISH",
                        "quantity": quantity,
                        "entry_price": None,
                        "exit_price": price,
                        "pnl": pnl,
                        "outcome": "win" if pnl > 0 else "loss" if pnl < 0 else "closed",
                        "source": _source(fill),
                    }
                )
                continue
            closing = min(quantity, cycle["open_qty"])
            cycle["open_qty"] -= closing
            cycle["closed_qty"] += closing
            cycle["exit_value"] += closing * price
            cycle["pnl"] += _number(fill.get("realizedPnl"))
            if cycle["open_qty"] <= 1e-12:
                pnl = cycle["pnl"]
                closed.append(
                    {
                        "entry_time": cycle["entry_time"],
                        "exit_time": _timestamp(fill.get("time")),
                        "asset": fill.get("symbol"),
                        "side": side,
                        "trend": "BULLISH" if side == "LONG" else "BEARISH",
                        "quantity": cycle["closed_qty"],
                        "entry_price": cycle["entry_value"] / cycle["entry_qty"],
                        "exit_price": cycle["exit_value"] / cycle["closed_qty"],
                        "pnl": pnl,
                        "outcome": "win" if pnl > 0 else "loss" if pnl < 0 else "closed",
                        "source": _source(cycle["row"]),
                    }
                )
                del open_cycles[key]
    return closed, open_cycles


def _display_trades(positions: list[dict[str, Any]], fills: list[dict[str, Any]], protection_orders: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Map real Binance positions and fill cycles to the dashboard trade shape."""
    protection_orders = protection_orders or []
    closed, open_cycles = _closed_fill_cycles(fills)

    def trigger(position: dict[str, Any], order_type: str) -> Any:
        order = next(
            (
                order
                for order in protection_orders
                if order.get("_account_id") == position.get("_account_id")
                if order.get("symbol") == position.get("symbol")
                and order.get("positionSide") == position.get("positionSide")
                and order.get("orderType", order.get("type")) == order_type
            ),
            None,
        )
        return order.get("triggerPrice", order.get("stopPrice")) if order else None

    active = [
        {
            "entry_time": open_cycles.get((position.get("_account_id"), position.get("symbol"), position.get("positionSide")), {}).get("entry_time") or _timestamp(position.get("updateTime")),
            "exit_time": None,
            "asset": position.get("symbol"),
            "side": position.get("positionSide"),
            "trend": "BULLISH" if position.get("positionSide") == "LONG" else "BEARISH",
            "quantity": abs(_number(position.get("positionAmt"))),
            "entry_price": position.get("entryPrice"),
            "mark_price": position.get("markPrice"),
            "take_profit": trigger(position, "TAKE_PROFIT_MARKET"),
            "stop_loss": trigger(position, "STOP_MARKET"),
            "liquidation_price": position.get("liquidationPrice"),
            "leverage": position.get("leverage"),
            "exit_price": None,
            "pnl": position.get("unRealizedProfit"),
            "outcome": "open",
            "source": _source(position),
        }
        for position in positions
    ]
    return sorted([*active, *closed], key=lambda trade: str(trade.get("entry_time") or trade.get("exit_time") or ""), reverse=True)


def _exchange_snapshot(accounts: list[dict[str, Any]], assets: list[str]) -> dict[str, Any]:
    """Read account state from Binance without placing or modifying anything."""
    import httpx

    from Live._client import BinanceClient
    from Live.Crypto import load_credential

    wallets: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    protection_orders: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for account in accounts:
        account_id = str(account["id"])
        environment = str(account.get("environment") or "testnet")
        if account.get("environment") == "paper":
            continue
        base_url = "https://fapi.binance.com" if account.get("environment") == "real" else "https://testnet.binancefuture.com"
        try:
            api_key, api_secret = load_credential(account_id)
            with BinanceClient(base_url, api_key=api_key, api_secret=api_secret) as client:
                balance = client.get("/fapi/v2/account")
                risk = client.get("/fapi/v2/positionRisk")
                active_positions = [row for row in risk if _number(row.get("positionAmt")) != 0] if isinstance(risk, list) else []
                for asset in {str(row["symbol"]) for row in active_positions}:
                    result = client.protection_orders(asset)
                    if isinstance(result, list):
                        protection_orders.extend({**row, "_account_id": account_id, "_environment": environment} for row in result)
                for asset in sorted({*assets, *(str(row["symbol"]) for row in active_positions)}):
                    result = client.get("/fapi/v1/userTrades", symbol=asset, limit=1000)
                    if isinstance(result, list):
                        trades.extend({**row, "_account_id": account_id, "_environment": environment} for row in result)
            usdt = next((row for row in balance.get("assets", []) if row.get("asset") == "USDT"), {})
            wallets.append({**usdt, "_account_id": account_id, "_environment": environment})
            if isinstance(risk, list):
                positions.extend({**row, "_account_id": account_id, "_environment": environment} for row in active_positions)
        except (httpx.HTTPError, KeyError, OSError, RuntimeError, TypeError, ValueError):
            log.warning("exchange snapshot failed for account %s", account_id)
            errors.append({"account_id": account_id, "error": "exchange unavailable"})
    return {"wallets": wallets, "positions": positions, "trades": trades, "protection_orders": protection_orders, "errors": errors}


def build_dashboard(user_id: str, leverage: float, configured_assets: list[str], account_id: str | None = None) -> dict[str, Any]:
    """Return aggregate dashboard data scoped only to ``user_id``."""
    from SharedParams.Supabase import get_service_client

    db = get_service_client()
    all_accounts = _rows(db.table("exchange_accounts").select("id,label,environment").eq("user_id", user_id).execute())
    selected_account_id = account_id or (str(all_accounts[0]["id"]) if all_accounts else None)
    accounts = [account for account in all_accounts if str(account["id"]) == selected_account_id]
    account_ids = [str(account["id"]) for account in accounts]
    positions: list[dict[str, Any]] = []
    equity: list[dict[str, Any]] = []
    for account_id in account_ids:
        positions.extend(_rows(db.table("live_positions").select("*").eq("account_id", account_id).execute()))
        equity.extend(_rows(db.table("equity_snapshots").select("*").eq("account_id", account_id).order("ts", desc=False).limit(500).execute()))

    assets = sorted({*configured_assets, *(str(row.get("asset")) for row in positions if row.get("asset"))})
    exchange = _exchange_snapshot(accounts, assets) if accounts else {"wallets": [], "positions": [], "trades": [], "protection_orders": [], "errors": []}
    exchange_positions = exchange["positions"]
    exchange_trades = exchange["trades"]
    display_trades = _display_trades(exchange_positions, exchange_trades, exchange["protection_orders"])
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
        "selected_account_id": selected_account_id,
        "assets": assets,
        "trades": display_trades,
        "positions": exchange_positions or positions,
        "equity": equity,
        "exchange_errors": exchange.get("errors", []),
        "stats": {
            "data_source": f"binance-{accounts[0].get('environment', 'testnet')}-exchange" if accounts else "not-configured",
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
