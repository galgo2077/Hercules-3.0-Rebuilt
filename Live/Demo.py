"""Binance Demo (testnet) execution engine — candle-driven live loop."""
from __future__ import annotations

import asyncio
import json
import logging
import tomllib
from pathlib import Path
from typing import Any

import websockets

from Live._client import BinanceClient
from Live.Positions import PositionTracker

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]
_LIVE_TOML = _ROOT / "Live.toml"
_PORTFOLIO_TOML = _ROOT / "Portfolio.toml"

_DEMO_REST = "https://testnet.binancefuture.com"
_DEMO_WS = "wss://stream.binancefuture.com/stream"


def _load_config() -> tuple[dict, dict]:
    with _LIVE_TOML.open("rb") as f:
        live = tomllib.load(f)
    with _PORTFOLIO_TOML.open("rb") as f:
        pf = tomllib.load(f)
    return live, pf


def _stream_url(assets: list[str], interval: str) -> str:
    streams = "/".join(f"{a.lower()}@kline_{interval}" for a in assets)
    return f"{_DEMO_WS}?streams={streams}"


class DemoEngine:
    """Runs strategy → execute loop against Binance demo futures."""

    def __init__(self) -> None:
        self._live, self._pf = _load_config()
        self._assets: list[str] = list(self._pf.get("assets", {}).keys())
        self._interval: str = self._live.get("interval", "1h")
        self._reconnect: int = int(self._live.get("reconnect_delay_s", 5))
        self._tracker = PositionTracker()
        self._running = False
        self._ohlcv_buf: dict[str, list[dict]] = {a: [] for a in self._assets}

    def _allocations(self, initial_cash: float) -> dict[str, float]:
        weights = self._pf.get("weights", {})
        return {a: initial_cash * weights.get(a, 0.0) for a in self._assets}

    def _on_closed_candle(self, client: BinanceClient, msg: dict[str, Any]) -> None:
        from Dataframe.Frame import build
        from Strategy.Strategy import evaluate

        stream = msg.get("stream", "")
        asset = stream.split("@")[0].upper() + "USDT" if "@" in stream else ""
        k = msg.get("data", {}).get("k", {})
        if not k.get("x") or asset not in self._assets:
            return

        self._ohlcv_buf[asset].append({
            "timestamp": k["t"], "open": float(k["o"]), "high": float(k["h"]),
            "low": float(k["l"]), "close": float(k["c"]), "volume": float(k["v"]),
            "asset": asset,
        })
        if len(self._ohlcv_buf[asset]) < 200:
            return

        import polars as pl
        ohlcv = pl.DataFrame(self._ohlcv_buf[asset]).with_columns(
            pl.from_epoch(pl.col("timestamp"), time_unit="ms").alias("timestamp")
        )
        frame = build(ohlcv)
        cash = float(self._pf.get("initial_cash", 100.0))
        allocs = self._allocations(cash)
        exposures = self._tracker.as_exposure_dict(allocs)
        decisions = evaluate(frame.filter(pl.col("asset") == asset), asset_exposures=exposures)

        last = decisions.filter(pl.col("asset") == asset).sort("timestamp").tail(1)
        if last.is_empty():
            return

        row = last.row(0, named=True)
        self._execute(client, row, allocs)

    def _execute(self, client: BinanceClient, row: dict, allocs: dict[str, float]) -> None:
        from Live.Orders import Long, Short

        asset = row["asset"]
        action = row.get("action", "Hold")
        allocated = allocs.get(asset, 0.0)
        leverage = int(self._pf.get("leverage", {}).get(asset, 1))

        if action == "Entry" and row.get("side") == "Long":
            log.info("DEMO ENTRY LONG %s %.2f USDT", asset, allocated)
            Long.enter(client, asset, allocated, leverage)
        elif action == "Entry" and row.get("side") == "Short":
            log.info("DEMO ENTRY SHORT %s %.2f USDT", asset, allocated)
            Short.enter(client, asset, allocated, leverage)
        elif row.get("exit_required"):
            pos = self._tracker.get(asset)
            if pos.side == "LONG":
                log.info("DEMO EXIT LONG %s", asset)
                Long.exit(client, asset)
            elif pos.side == "SHORT":
                log.info("DEMO EXIT SHORT %s", asset)
                Short.exit(client, asset)

    async def _listen(self) -> None:
        url = _stream_url(self._assets, self._interval)
        with BinanceClient(_DEMO_REST) as client:
            self._tracker.fetch(client)
            async with websockets.connect(url) as ws:
                async for raw in ws:
                    if not self._running:
                        break
                    try:
                        msg = json.loads(raw)
                        self._on_closed_candle(client, msg)
                    except Exception:
                        log.exception("Demo candle handler error")

    def start(self) -> None:
        self._running = True
        asyncio.run(self._run_loop())

    def stop(self) -> None:
        self._running = False

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._listen()
            except Exception:
                log.exception("Demo WS disconnected — reconnecting in %ds", self._reconnect)
                await asyncio.sleep(self._reconnect)
