"""Long-position compatibility wrappers around canonical execution."""

from __future__ import annotations

from typing import Any

from Live.Execution import enter_position, exit_position


def enter(
    client: Any,
    symbol: str,
    usdt_amount: float,
    leverage: int = 1,
    *,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
) -> dict[str, Any]:
    return enter_position(
        client,
        symbol,
        "LONG",
        usdt_amount,
        leverage,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )


def exit(client: Any, symbol: str, quantity: float | None = None) -> dict[str, Any]:
    return exit_position(client, symbol, "LONG", quantity)
