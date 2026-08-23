"""Long position order execution — market entry and exit."""

from __future__ import annotations

from typing import Any

from Live._client import BinanceClient


def enter(client: BinanceClient, symbol: str, usdt_amount: float, leverage: int = 1) -> dict[str, Any]:
    """Open or add to a long position via MARKET BUY."""
    client.set_leverage(symbol, leverage)
    price_data = client.get("/fapi/v1/ticker/price", symbol=symbol)
    price = float(price_data["price"])
    qty = round(usdt_amount * leverage / price, 3)
    return client.post(
        "/fapi/v1/order",
        symbol=symbol,
        side="BUY",
        type="MARKET",
        quantity=qty,
        positionSide="LONG",
    )


def exit(client: BinanceClient, symbol: str, quantity: float | None = None) -> dict[str, Any]:
    """Close a long position — MARKET SELL with explicit qty (hedge mode requires quantity, not closePosition)."""
    if quantity is None:
        positions = client.get("/fapi/v2/positionRisk")
        pos = next((p for p in positions if p["symbol"] == symbol and p["positionSide"] == "LONG"), None)
        quantity = abs(float(pos["positionAmt"])) if pos else 0.0
    return client.post(
        "/fapi/v1/order",
        symbol=symbol,
        side="SELL",
        type="MARKET",
        positionSide="LONG",
        quantity=round(quantity, 3),
    )
