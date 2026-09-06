"""Thin Binance USDT-M Futures REST client — HMAC-SHA256 signed requests."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 10.0
class BinanceClient:
    """Minimal signed REST client for Binance USDT-M Futures."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key or os.environ["BINANCE_API_KEY"]
        self._secret = (api_secret or os.environ["BINANCE_API_SECRET"]).encode()
        self._http = httpx.Client(timeout=_TIMEOUT, headers={"X-MBX-APIKEY": self._key})
        self._tick_cache: dict[str, float] = {}
        self._quantity_cache: dict[str, dict[str, float]] = {}

    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        qs = urlencode(params)
        sig = hmac.new(self._secret, qs.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    def _get_public(self, path: str, **params: Any) -> Any:
        """Unsigned GET for public endpoints (exchange info, etc.)."""
        r = self._http.get(f"{self._base}{path}", params=params)
        r.raise_for_status()
        return r.json()

    def get(self, path: str, **params: Any) -> Any:
        r = self._http.get(f"{self._base}{path}", params=self._sign(params))
        r.raise_for_status()
        return r.json()

    def post(self, path: str, **params: Any) -> Any:
        r = self._http.post(f"{self._base}{path}", data=self._sign(params))
        r.raise_for_status()
        return r.json()

    def delete(self, path: str, **params: Any) -> Any:
        r = self._http.delete(f"{self._base}{path}", params=self._sign(params))
        r.raise_for_status()
        return r.json()

    def set_leverage(self, symbol: str, leverage: int) -> None:
        self.post("/fapi/v1/leverage", symbol=symbol, leverage=leverage)

    def place_protection(self, **params: Any) -> Any:
        """Place a conditional exit through Binance's algo-order API."""
        params["algoType"] = "CONDITIONAL"
        params["triggerPrice"] = params.pop("stopPrice")
        return self.post("/fapi/v1/algoOrder", **params)

    def protection_orders(self, symbol: str) -> Any:
        return self.get("/fapi/v1/openAlgoOrders", symbol=symbol)

    def cancel_protection(self, symbol: str, algo_id: int) -> Any:
        return self.delete("/fapi/v1/algoOrder", symbol=symbol, algoId=algo_id)

    def tick_size(self, symbol: str) -> float:
        """Return price tickSize for symbol, cached after first query."""
        if symbol not in self._tick_cache:
            info = self._get_public("/fapi/v1/exchangeInfo", symbol=symbol)
            sym_info = next(s for s in info["symbols"] if s["symbol"] == symbol)
            price_filter = next(f for f in sym_info["filters"] if f["filterType"] == "PRICE_FILTER")
            self._tick_cache[symbol] = float(price_filter["tickSize"])
        return self._tick_cache[symbol]

    def quantity_filters(self, symbol: str) -> dict[str, float]:
        if symbol not in self._quantity_cache:
            info = self._get_public("/fapi/v1/exchangeInfo", symbol=symbol)
            sym_info = next(s for s in info["symbols"] if s["symbol"] == symbol)
            filters = {f["filterType"]: f for f in sym_info["filters"]}
            lot = filters.get("MARKET_LOT_SIZE", filters["LOT_SIZE"])
            if float(lot.get("stepSize", 0)) <= 0:
                lot = filters["LOT_SIZE"]
            notional = filters.get("MIN_NOTIONAL", filters.get("NOTIONAL", {}))
            self._quantity_cache[symbol] = {
                "step_size": float(lot["stepSize"]),
                "min_qty": float(lot["minQty"]),
                "min_notional": float(notional.get("notional", 0)),
            }
        return self._quantity_cache[symbol]

    def round_price(self, symbol: str, price: float, direction: str = "nearest") -> float:
        """Round price to exchange tickSize for symbol."""
        tick = Decimal(str(self.tick_size(symbol)))
        rounding = {"down": ROUND_DOWN, "nearest": ROUND_HALF_UP, "up": ROUND_UP}.get(direction)
        if rounding is None:
            raise ValueError(f"invalid price rounding direction: {direction}")
        return float((Decimal(str(price)) / tick).to_integral_value(rounding=rounding) * tick)

    def ensure_hedge_mode(self) -> None:
        """Enable dual-position (hedge) mode if not already on.

        positionSide=LONG/SHORT only works in hedge mode.
        Binance returns -4061 for every order if one-way mode is active.
        """
        try:
            resp = self.get("/fapi/v1/positionSide/dual")
            if not resp.get("dualSidePosition", False):
                self.post("/fapi/v1/positionSide/dual", dualSidePosition="true")
                log.info("Hedge mode enabled for account")
            else:
                log.debug("Hedge mode already active")
        except Exception as exc:
            log.error("ensure_hedge_mode failed — orders WILL fail: %s", exc)
            raise

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "BinanceClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
