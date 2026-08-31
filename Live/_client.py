"""Thin Binance USDT-M Futures REST client — HMAC-SHA256 signed requests."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlencode

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 10.0
_tick_cache: dict[str, float] = {}
_symbol_filters: dict[str, tuple[Decimal, Decimal, Decimal]] = {}


class BinanceAPIError(RuntimeError):
    """Exchange rejection retaining HTTP status and Binance error payload."""


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

    def _sign(self, params: dict) -> dict:
        signed = dict(params)
        signed["timestamp"] = int(time.time() * 1000)
        qs = urlencode(signed)
        sig = hmac.new(self._secret, qs.encode(), hashlib.sha256).hexdigest()
        signed["signature"] = sig
        return signed

    def _request_error(self, response: httpx.Response) -> BinanceAPIError:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        return BinanceAPIError(f"Binance HTTP {response.status_code}: {payload}")

    def _get_public(self, path: str, **params: Any) -> Any:
        """Unsigned GET for public endpoints (exchange info, etc.)."""
        r = self._http.get(f"{self._base}{path}", params=params)
        if r.is_error:
            raise self._request_error(r)
        return r.json()

    def get(self, path: str, **params: Any) -> Any:
        r = self._http.get(f"{self._base}{path}", params=self._sign(params))
        if r.is_error:
            raise self._request_error(r)
        return r.json()

    def post(self, path: str, **params: Any) -> Any:
        r = self._http.post(f"{self._base}{path}", data=self._sign(params))
        if r.is_error:
            raise self._request_error(r)
        return r.json()

    def delete(self, path: str, **params: Any) -> Any:
        r = self._http.delete(f"{self._base}{path}", params=self._sign(params))
        if r.is_error:
            raise self._request_error(r)
        return r.json()

    def set_leverage(self, symbol: str, leverage: int) -> None:
        self.post("/fapi/v1/leverage", symbol=symbol, leverage=leverage)

    def tick_size(self, symbol: str) -> float:
        """Return price tickSize for symbol, cached after first query."""
        if symbol not in _tick_cache:
            info = self._get_public("/fapi/v1/exchangeInfo", symbol=symbol)
            sym_info = next(s for s in info["symbols"] if s["symbol"] == symbol)
            price_filter = next(f for f in sym_info["filters"] if f["filterType"] == "PRICE_FILTER")
            _tick_cache[symbol] = float(price_filter["tickSize"])
        return _tick_cache[symbol]

    def quantity(self, symbol: str, usdt_notional: float, price: float) -> str:
        """Return filter-compliant quantity; amount is leveraged notional."""
        if usdt_notional <= 0 or price <= 0:
            raise ValueError("usdt_notional and price must be positive")
        if symbol not in _symbol_filters:
            info = self._get_public("/fapi/v1/exchangeInfo", symbol=symbol)
            sym = next(s for s in info["symbols"] if s["symbol"] == symbol)
            filters = {f["filterType"]: f for f in sym["filters"]}
            notional_filter = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL") or {}
            lot_filter = filters.get("MARKET_LOT_SIZE") or filters["LOT_SIZE"]
            _symbol_filters[symbol] = (
                Decimal(lot_filter["stepSize"]),
                Decimal(lot_filter["minQty"]),
                Decimal(notional_filter.get("notional", notional_filter.get("minNotional", "0"))),
            )
        step, minimum, min_notional = _symbol_filters[symbol]
        qty = (Decimal(str(usdt_notional)) / Decimal(str(price))).quantize(step, rounding=ROUND_DOWN)
        if qty < minimum or qty * Decimal(str(price)) < min_notional:
            raise ValueError(f"{symbol} order below exchange minimum: qty={qty}, notional={qty * Decimal(str(price))}")
        return format(qty, "f")

    def normalize_quantity(self, symbol: str, quantity: float) -> str:
        """Floor explicit position quantity to LOT_SIZE; reject zero."""
        if quantity <= 0:
            raise ValueError(f"{symbol} has no quantity to close")
        if symbol not in _symbol_filters:
            self.quantity(symbol, 1_000_000.0, 1.0)
        step, minimum, _ = _symbol_filters[symbol]
        normalized = Decimal(str(quantity)).quantize(step, rounding=ROUND_DOWN)
        if normalized < minimum or normalized <= 0:
            raise ValueError(f"{symbol} position quantity below exchange minimum: {normalized}")
        return format(normalized, "f")

    def round_price(self, symbol: str, price: float) -> float:
        """Round price to exchange tickSize for symbol."""
        tick = Decimal(str(self.tick_size(symbol)))
        rounded = (Decimal(str(price)) / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick
        return float(rounded)

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
