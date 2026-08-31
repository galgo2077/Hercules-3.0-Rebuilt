"""Binance Real production execution engine — same loop as Demo, production endpoints."""

from __future__ import annotations

import asyncio
import json
import logging

import websockets

from Live.Demo import DemoEngine, _load_config

log = logging.getLogger(__name__)

_REAL_REST = "https://fapi.binance.com"
_REAL_WS = "wss://fstream.binance.com/stream"


def _assert_real_mode() -> None:
    live, _ = _load_config()
    if live.get("mode") != "real":
        raise RuntimeError("Live.toml mode must be 'real' to start RealEngine")


def _stream_url(assets: list[str], interval: str) -> str:
    streams = "/".join(f"{a.lower()}@kline_{interval}" for a in assets)
    return f"{_REAL_WS}?streams={streams}"


class RealEngine(DemoEngine):
    """Production engine — inherits full candle loop from DemoEngine, uses live endpoints.

    api_key / api_secret: live account credentials (from DB via load_credential).
    label: account identifier shown in logs.
    Refuses to start unless Live.toml mode == 'real'.
    """

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None, label: str = "real") -> None:
        super().__init__(api_key=api_key, api_secret=api_secret, label=label)
        # Override rest URL to production endpoint
        self._rest_url = _REAL_REST
        self._major_tom_environment = "PRODUCTION"

    def start(self) -> None:
        _assert_real_mode()
        log.warning("[%s] STARTING REAL PRODUCTION ENGINE — live funds at risk", self._label)
        self._running = True
        asyncio.run(self._run_loop())

    async def _listen(self) -> None:
        url = _stream_url(self._assets, self._interval)
        with self._client() as client:
            self._tracker.fetch(client)
            async with websockets.connect(url) as ws:
                async for raw in ws:
                    if not self._running:
                        break
                    try:
                        self._dispatch_candle(client, json.loads(raw))
                    except Exception:
                        log.exception("[%s] candle dispatch error", self._label)
