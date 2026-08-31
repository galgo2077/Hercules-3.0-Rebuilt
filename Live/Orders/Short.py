"""Short position order execution — market entry with SL/TP, market exit."""

from __future__ import annotations

import logging
from typing import Any

from Live._client import BinanceClient

log = logging.getLogger(__name__)


def _round(client: Any, symbol: str, price: float) -> float:
    """Round price to exchange tickSize. Falls back to 8 decimals for mock clients."""
    fn = getattr(client, "round_price", None)
    return fn(symbol, price) if fn is not None else round(price, 8)


def enter(
    client: BinanceClient,
    symbol: str,
    usdt_amount: float,
    leverage: int = 1,
    *,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
) -> dict[str, Any]:
    """Open a short position via MARKET SELL, then place SL and TP orders.

    SL/TP failures are logged but do NOT abort — entry is already filled.
    Caller must monitor positions if SL/TP placement fails.
    """
    client.set_leverage(symbol, leverage)
    price_data = client.get("/fapi/v1/ticker/price", symbol=symbol)
    price = float(price_data["price"])
    qty = client.quantity(symbol, usdt_amount, price) if hasattr(client, "quantity") else round(usdt_amount / price, 3)
    entry = client.post(
        "/fapi/v1/order",
        symbol=symbol,
        side="SELL",
        type="MARKET",
        quantity=qty,
        positionSide="SHORT",
    )

    # SL above entry (short loses when price rises)
    if stop_loss_pct is not None:
        sl_price = _round(client, symbol, price * (1.0 + stop_loss_pct))
        try:
            client.post(
                "/fapi/v1/order",
                symbol=symbol,
                side="BUY",
                type="STOP_MARKET",
                stopPrice=sl_price,
                positionSide="SHORT",
                quantity=qty,
            )
        except Exception as exc:
            log.error("SL order failed for %s short @ sl=%.4f — position NAKED: %s", symbol, sl_price, exc)

    # TP below entry (short profits when price falls)
    if take_profit_pct is not None:
        tp_price = _round(client, symbol, price * (1.0 - take_profit_pct))
        try:
            client.post(
                "/fapi/v1/order",
                symbol=symbol,
                side="BUY",
                type="TAKE_PROFIT_MARKET",
                stopPrice=tp_price,
                positionSide="SHORT",
                quantity=qty,
            )
        except Exception as exc:
            log.error("TP order failed for %s short @ tp=%.4f — position NAKED: %s", symbol, tp_price, exc)

    return entry


def exit(client: BinanceClient, symbol: str, quantity: float | None = None) -> dict[str, Any]:
    """Close a short position — MARKET BUY with explicit qty (hedge mode requires quantity, not closePosition)."""
    if quantity is None:
        positions = client.get("/fapi/v2/positionRisk")
        pos = next((p for p in positions if p["symbol"] == symbol and p["positionSide"] == "SHORT"), None)
        quantity = abs(float(pos["positionAmt"])) if pos else 0.0
    quantity = client.normalize_quantity(symbol, quantity) if hasattr(client, "normalize_quantity") else round(quantity, 8)
    if float(quantity) <= 0:
        raise ValueError(f"{symbol} has no short position to close")
    return client.post(
        "/fapi/v1/order",
        symbol=symbol,
        side="BUY",
        type="MARKET",
        positionSide="SHORT",
        quantity=quantity,
    )
