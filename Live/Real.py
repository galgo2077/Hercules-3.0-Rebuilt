"""Binance Real production execution engine — same loop as Demo, production endpoints."""

from __future__ import annotations

import asyncio
import logging

from Live.Demo import DemoEngine

log = logging.getLogger(__name__)

_REAL_REST = "https://fapi.binance.com"
_REAL_WS = "wss://fstream.binance.com/stream"


class RealEngine(DemoEngine):
    """Production engine — inherits full candle loop from DemoEngine, uses live endpoints.

    api_key / api_secret: live account credentials (from DB via load_credential).
    label: account identifier shown in logs.
    Selection is controlled by the validated account environment in AccountWorker.
    """

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None, label: str = "real", account_id: str | None = None) -> None:
        super().__init__(api_key=api_key, api_secret=api_secret, label=label, account_id=account_id)
        # Override rest URL to production endpoint
        self._rest_url = _REAL_REST
        self._ws_url = _REAL_WS
        self._environment = "REAL"

    def start(self) -> None:
        log.warning("[%s] STARTING REAL PRODUCTION ENGINE — live funds at risk", self._label)
        self._running = True
        asyncio.run(self._run_loop())
