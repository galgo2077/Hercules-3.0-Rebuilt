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


def build_dashboard(user_id: str, leverage: float) -> dict[str, Any]:
    """Return aggregate dashboard data scoped only to ``user_id``."""
    from SharedParams.Supabase import get_service_client

    db = get_service_client()
    accounts = _rows(db.table("exchange_accounts").select("id,label,environment").eq("user_id", user_id).execute())
    account_ids = [str(account["id"]) for account in accounts]
    trades: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    equity: list[dict[str, Any]] = []
    for account_id in account_ids:
        trades.extend(_rows(db.table("trades").select("*").eq("account_id", account_id).order("entry_time", desc=True).limit(500).execute()))
        positions.extend(_rows(db.table("live_positions").select("*").eq("account_id", account_id).execute()))
        equity.extend(_rows(db.table("equity_snapshots").select("*").eq("account_id", account_id).order("ts", desc=False).limit(500).execute()))

    closed = [trade for trade in trades if trade.get("exit_time")]
    pnls = [_number(trade.get("pnl")) for trade in closed]
    winners = [pnl for pnl in pnls if pnl > 0]
    losers = [pnl for pnl in pnls if pnl < 0]
    latest_equity = _number(equity[-1].get("equity_usdt")) if equity else 0.0
    open_size = sum(_number(position.get("size_usdt")) for position in positions)
    assets = sorted({str(row.get("asset")) for row in [*trades, *positions] if row.get("asset")})
    win_streak, loss_streak = _streaks(closed)
    gross_profit, gross_loss = sum(winners), abs(sum(losers))
    return {
        "accounts": accounts,
        "assets": assets,
        "trades": trades[:100],
        "positions": positions,
        "equity": equity,
        "stats": {
            "equity_usdt": latest_equity,
            "available_usdt": latest_equity - open_size,
            "max_leverage": leverage,
            "max_drawdown_usdt": _drawdown(_number(row.get("equity_usdt")) for row in equity),
            "pnl_usdt": sum(pnls),
            "win_rate": len(winners) / len(closed) if closed else 0.0,
            "profit_factor": gross_profit / gross_loss if gross_loss else None,
            "longs": sum(1 for trade in trades if trade.get("side") == "LONG"),
            "shorts": sum(1 for trade in trades if trade.get("side") == "SHORT"),
            "gross_profit_usdt": gross_profit,
            "gross_loss_usdt": gross_loss,
            "expectancy_usdt": sum(pnls) / len(closed) if closed else 0.0,
            "best_trade_usdt": max(pnls, default=0.0),
            "worst_trade_usdt": min(pnls, default=0.0),
            "consecutive_wins": win_streak,
            "consecutive_losses": loss_streak,
            "unrealized_pnl_usdt": 0.0,
            "fill_count": len(trades),
            "position_size": open_size,
            "funding_rate": None,
            "open_mismatches": 0,
        },
    }
