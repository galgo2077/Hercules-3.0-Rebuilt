"""Shared Binance execution primitives used by demo and real engines."""

from __future__ import annotations

import re
from decimal import ROUND_DOWN, Decimal
from math import isfinite
from time import sleep
from typing import Any


def stream_asset(stream: object, assets: set[str] | list[str]) -> str | None:
    """Return the exact configured symbol from a Binance combined-stream name."""
    if not isinstance(stream, str) or re.fullmatch(r"[a-z0-9]+@kline_(?:1m|3m|5m|15m|30m|1h|2h|4h|6h|8h|12h|1d|3d|1w|1M)", stream) is None:
        return None
    symbol = stream.split("@", 1)[0].upper()
    return symbol if symbol in assets else None


def quantize_quantity(quantity: float, step_size: float) -> float:
    if not isfinite(quantity) or quantity <= 0 or not isfinite(step_size):
        raise ValueError("quantity and step must be finite and positive")
    step = Decimal(str(step_size))
    if step <= 0:
        raise ValueError("quantity step must be positive")
    return float((Decimal(str(quantity)) / step).to_integral_value(rounding=ROUND_DOWN) * step)


def order_quantity(client: Any, symbol: str, notional_usdt: float, price: float) -> float:
    """Convert final leveraged notional to exchange-filtered quantity."""
    if price <= 0 or notional_usdt <= 0:
        raise ValueError("price and notional must be positive")
    filters = client.quantity_filters(symbol) if hasattr(client, "quantity_filters") else {"step_size": 0.001, "min_qty": 0, "min_notional": 0}
    quantity = quantize_quantity(notional_usdt / price, float(filters["step_size"]))
    if quantity < float(filters.get("min_qty", 0)) or quantity * price < float(filters.get("min_notional", 0)):
        raise ValueError(f"quantity below exchange minimum for {symbol}")
    return quantity


def _position(client: Any, symbol: str, side: str, attempts: int = 1) -> dict[str, Any] | None:
    for attempt in range(attempts):
        positions = client.get("/fapi/v2/positionRisk")
        if not isinstance(positions, list):
            raise RuntimeError("exchange returned invalid position state")
        found = next(
            (position for position in positions if position.get("symbol") == symbol and position.get("positionSide") == side and abs(float(position.get("positionAmt", 0))) > 1e-12),
            None,
        )
        if found is not None:
            return found
        if attempt + 1 < attempts:
            sleep(0.1)
    return None


def _cancel_protection(client: Any, symbol: str, side: str) -> None:
    orders = client.get("/fapi/v1/openOrders", symbol=symbol)
    if not isinstance(orders, list):
        raise RuntimeError("exchange returned invalid open-order state")
    for order in orders:
        if order.get("positionSide") == side:
            client.delete("/fapi/v1/order", symbol=symbol, orderId=order["orderId"])


def exit_position(client: Any, symbol: str, side: str, quantity: float | None = None) -> dict[str, Any]:
    """Close one hedge side with an explicit non-zero quantity."""
    if quantity is None:
        position = _position(client, symbol, side)
        if position is None:
            raise RuntimeError(f"cannot close missing {side} position for {symbol}")
        quantity = abs(float(position["positionAmt"]))
    filters = client.quantity_filters(symbol) if hasattr(client, "quantity_filters") else {"step_size": 0.001}
    quantity = quantize_quantity(quantity, float(filters["step_size"]))
    if quantity <= 0:
        raise ValueError(f"cannot close zero {side} quantity for {symbol}")
    result = client.post(
        "/fapi/v1/order",
        symbol=symbol,
        side="SELL" if side == "LONG" else "BUY",
        type="MARKET",
        positionSide=side,
        quantity=quantity,
    )
    _cancel_protection(client, symbol, side)
    if _position(client, symbol, side, attempts=3) is not None:
        raise RuntimeError(f"exchange did not confirm {side} close for {symbol}")
    return result


def enter_position(
    client: Any,
    symbol: str,
    side: str,
    notional_usdt: float,
    leverage: int,
    *,
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
) -> dict[str, Any]:
    """Open one hedge side and attach configured protection, or close it."""
    if side not in {"LONG", "SHORT"}:
        raise ValueError(f"invalid position side: {side}")
    if stop_loss_pct is None and take_profit_pct is None:
        raise ValueError("at least one protective exit is required")
    if any(not isfinite(value) or not 0 < value < 1 for value in (stop_loss_pct, take_profit_pct) if value is not None):
        raise ValueError("protective exit percentages must be between 0 and 1")
    client.set_leverage(symbol, leverage)
    ticker = client.get("/fapi/v1/ticker/price", symbol=symbol)
    reference_price = float(ticker["price"])
    requested_quantity = order_quantity(client, symbol, notional_usdt, reference_price)
    entry = client.post(
        "/fapi/v1/order",
        symbol=symbol,
        side="BUY" if side == "LONG" else "SELL",
        type="MARKET",
        quantity=requested_quantity,
        positionSide=side,
        newOrderRespType="RESULT",
    )
    if not isinstance(entry, dict):
        try:
            exit_position(client, symbol, side, requested_quantity)
        except Exception as close_error:
            raise RuntimeError(f"invalid {side} entry response and emergency close failed for {symbol}: {close_error}") from close_error
        raise RuntimeError(f"invalid {side} entry response; emergency close sent for {symbol}")
    position = _position(client, symbol, side, attempts=3)
    if position is None:
        emergency_quantity = float(entry.get("executedQty") or requested_quantity)
        try:
            exit_position(client, symbol, side, emergency_quantity)
        except Exception as close_error:
            raise RuntimeError(f"exchange did not confirm {side} entry and emergency close failed for {symbol}: {close_error}") from close_error
        raise RuntimeError(f"exchange did not confirm {side} entry; emergency close sent for {symbol}")
    quantity = abs(float(position["positionAmt"]))
    entry_price = float(position.get("entryPrice") or 0)
    if not isfinite(entry_price) or entry_price <= 0:
        try:
            exit_position(client, symbol, side, quantity)
        except Exception as close_error:
            raise RuntimeError(f"invalid {side} entry price and emergency close failed for {symbol}: {close_error}") from close_error
        raise RuntimeError(f"exchange returned invalid {side} entry price; position closed for {symbol}")
    close_side = "SELL" if side == "LONG" else "BUY"

    try:
        if stop_loss_pct is not None:
            stop = entry_price * (1.0 - stop_loss_pct if side == "LONG" else 1.0 + stop_loss_pct)
            client.post(
                "/fapi/v1/order",
                symbol=symbol,
                side=close_side,
                type="STOP_MARKET",
                stopPrice=client.round_price(symbol, stop, "down" if side == "LONG" else "up") if hasattr(client, "round_price") else round(stop, 8),
                positionSide=side,
                closePosition="true",
            )
        if take_profit_pct is not None:
            take = entry_price * (1.0 + take_profit_pct if side == "LONG" else 1.0 - take_profit_pct)
            client.post(
                "/fapi/v1/order",
                symbol=symbol,
                side=close_side,
                type="TAKE_PROFIT_MARKET",
                stopPrice=client.round_price(symbol, take, "up" if side == "LONG" else "down") if hasattr(client, "round_price") else round(take, 8),
                positionSide=side,
                closePosition="true",
            )
        expected = {order_type for configured, order_type in ((stop_loss_pct, "STOP_MARKET"), (take_profit_pct, "TAKE_PROFIT_MARKET")) if configured is not None}
        open_orders = client.get("/fapi/v1/openOrders", symbol=symbol)
        if not isinstance(open_orders, list) or not expected <= {order.get("type") for order in open_orders if order.get("positionSide") == side}:
            raise RuntimeError("exchange did not confirm required protection")
    except Exception as protection_error:
        cancel_error: Exception | None = None
        try:
            _cancel_protection(client, symbol, side)
        except Exception as exc:
            cancel_error = exc
        try:
            exit_position(client, symbol, side, quantity)
        except Exception as close_error:
            raise RuntimeError(f"{side} protection and emergency close failed for {symbol}: {close_error}") from protection_error
        if cancel_error is not None:
            raise RuntimeError(f"{side} protection failed; position closed but order cancellation failed for {symbol}: {cancel_error}") from protection_error
        raise RuntimeError(f"{side} protection failed; position closed for {symbol}") from protection_error
    return entry
