"""Thin Binance USDT-M Futures REST client — HMAC-SHA256 signed requests."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any
from urllib.parse import urlencode

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 10.0
_tick_cache: dict[str, float] = {}


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

    def round_price(self, symbol: str, price: float) -> float:
        """Round price to exchange tickSize for symbol."""
        tick = self.tick_size(symbol)
        # number of decimal places = count digits after decimal in tick (e.g. 0.10 → 1)
        decimals = max(0, -int(f"{tick:.10f}".rstrip("0").find(".")) + len(f"{tick:.10f}".rstrip("0").split(".")[1]))
        return round(round(price / tick) * tick, decimals)

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
