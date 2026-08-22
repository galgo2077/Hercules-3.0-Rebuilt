"""Short position order execution — market entry with SL/TP, market exit."""

from __future__ import annotations

from typing import Any

from Live._client import BinanceClient


def enter(
    client: BinanceClient,
    symbol: str,
    usdt_amount: float,
    leverage: int = 1,
    *,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
) -> dict[str, Any]:
    """Open a short position via MARKET SELL, then place SL and TP orders."""
    client.set_leverage(symbol, leverage)
    price_data = client.get("/fapi/v1/ticker/price", symbol=symbol)
    price = float(price_data["price"])
    qty = round(usdt_amount * leverage / price, 3)
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
        sl_price = round(price * (1.0 + stop_loss_pct), 2)
        client.post(
            "/fapi/v1/order",
            symbol=symbol,
            side="BUY",
            type="STOP_MARKET",
            stopPrice=sl_price,
            positionSide="SHORT",
            closePosition="true",
        )
    # TP below entry (short profits when price falls)
    if take_profit_pct is not None:
        tp_price = round(price * (1.0 - take_profit_pct), 2)
        client.post(
            "/fapi/v1/order",
            symbol=symbol,
            side="BUY",
            type="TAKE_PROFIT_MARKET",
            stopPrice=tp_price,
            positionSide="SHORT",
            closePosition="true",
        )
    return entry


def exit(client: BinanceClient, symbol: str, quantity: float | None = None) -> dict[str, Any]:
    """Close a short position — reduceOnly MARKET BUY."""
    params: dict[str, Any] = dict(
        symbol=symbol,
        side="BUY",
        type="MARKET",
        positionSide="SHORT",
    )
    if quantity is not None:
        params["quantity"] = round(quantity, 3)
    else:
        params["closePosition"] = "true"
    return client.post("/fapi/v1/order", **params)
