"""Binance Real production execution engine — same loop as Demo, production endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import tomllib
from pathlib import Path

import websockets

from Live._client import BinanceClient
from Live.Demo import DemoEngine

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]
_LIVE_TOML = _ROOT / "SharedData" / "Live.toml"

_REAL_REST = "https://fapi.binance.com"
_REAL_WS = "wss://fstream.binance.com/stream"


def _assert_real_mode() -> None:
    with _LIVE_TOML.open("rb") as f:
        live = tomllib.load(f)
    if live.get("mode") != "real":
        raise RuntimeError("Live.toml mode must be 'real' to start RealEngine")


def _stream_url(assets: list[str], interval: str) -> str:
    streams = "/".join(f"{a.lower()}@kline_{interval}" for a in assets)
    return f"{_REAL_WS}?streams={streams}"


class RealEngine(DemoEngine):
    """Production engine — inherits candle loop from DemoEngine, uses live endpoints.

    Refuses to start unless Live.toml mode == 'real'.
    """

    def start(self) -> None:
        _assert_real_mode()
        log.warning("STARTING REAL PRODUCTION ENGINE — live funds at risk")
        self._running = True
        asyncio.run(self._run_loop())

    async def _listen(self) -> None:
        url = _stream_url(self._assets, self._interval)
        with BinanceClient(_REAL_REST) as client:
            self._tracker.fetch(client)
            async with websockets.connect(url) as ws:
                async for raw in ws:
                    if not self._running:
                        break
                    try:
                        msg = json.loads(raw)
                        self._on_closed_candle(client, msg)
                    except Exception:
                        log.exception("Real candle handler error")
