"""Admin-triggered Binance Futures position closure."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, Field


class ManualCloseRequest(BaseModel):
    """Exact hedge-mode position selected by an administrator."""

    account_id: str = Field(min_length=1, max_length=128)
    symbol: str = Field(pattern=r"^[A-Z0-9]{3,20}$")
    position_side: Literal["LONG", "SHORT"]


class PositionNotOpenError(RuntimeError):
    """Requested position has already become flat."""


def close_position(request: ManualCloseRequest, environment: str) -> dict[str, str | int]:
    """Re-read then market-close one exact Binance hedge-mode position."""
    from Live.Crypto import load_credential
    from Live._client import BinanceClient

    base_url = "https://fapi.binance.com" if environment == "real" else "https://testnet.binancefuture.com"
    api_key, api_secret = load_credential(request.account_id)
    with BinanceClient(base_url, api_key=api_key, api_secret=api_secret) as client:
        risks = client.get("/fapi/v2/positionRisk")
        position = next(
            (
                row for row in risks
                if row.get("symbol") == request.symbol and row.get("positionSide") == request.position_side
            ),
            None,
        )
        try:
            amount = Decimal(str(position.get("positionAmt", "0"))) if position else Decimal("0")
        except InvalidOperation as exc:
            raise PositionNotOpenError("exchange returned invalid position amount") from exc
        if amount == 0:
            raise PositionNotOpenError("position is no longer open")

        response = client.post(
            "/fapi/v1/order",
            symbol=request.symbol,
            side="SELL" if request.position_side == "LONG" else "BUY",
            type="MARKET",
            positionSide=request.position_side,
            quantity=format(abs(amount), "f"),
        )
    return {
        "symbol": request.symbol,
        "position_side": request.position_side,
        "quantity": format(abs(amount), "f"),
        "order_id": int(response.get("orderId", 0)),
    }
