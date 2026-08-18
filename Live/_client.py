"""Thin Binance USDT-M Futures REST client — HMAC-SHA256 signed requests."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any
from urllib.parse import urlencode

import httpx

_TIMEOUT = 10.0


class BinanceClient:
    """Minimal signed REST client for Binance USDT-M Futures."""

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")
        self._key = os.environ["BINANCE_API_KEY"]
        self._secret = os.environ["BINANCE_API_SECRET"].encode()
        self._http = httpx.Client(timeout=_TIMEOUT, headers={"X-MBX-APIKEY": self._key})

    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        qs = urlencode(params)
        sig = hmac.new(self._secret, qs.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

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

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "BinanceClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
