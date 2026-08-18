"""Paper trading engine — identical interface to DemoEngine, no real orders."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import websockets

from Dataframe.CandleBuffer import CandleBuffer
from Live.Risk import RiskState, check_entry, on_entry, on_exit, size_trade

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]
_DEMO_WS = "wss://stream.binancefuture.com/stream"
_MIN_BARS = 200


def _load_config() -> tuple[dict, dict]:
    with (_ROOT / "Live.toml").open("rb") as f:
        live = tomllib.load(f)
    with (_ROOT / "Portfolio.toml").open("rb") as f:
        pf = tomllib.load(f)
    return live, pf


@dataclass
class VirtualPosition:
    asset: str
    side: str        # LONG | SHORT | FLAT
    entry_price: float = 0.0
    size_usdt: float = 0.0
    open_time: float = field(default_factory=time.time)


@dataclass
class PaperTrade:
    asset: str
    side: str
    entry_price: float
    exit_price: float
    size_usdt: float
    pnl: float


class PaperEngine:
    """Simulates live execution with virtual positions and P&L tracking."""

    def __init__(self) -> None:
        self._live, self._pf = _load_config()
        self._assets: list[str] = list(self._pf.get("allocation", {}).keys())
        self._interval: str = self._live.get("interval", "1h")
        self._reconnect: int = int(self._live.get("reconnect_delay_s", 5))
        self._buffer = CandleBuffer(capacity=600)
        self._positions: dict[str, VirtualPosition] = {}
        self._trades: list[PaperTrade] = []
        self._running = False
        cash = float(self._pf.get("initial_cash", 100.0))
        self._risk = RiskState(
            initial_equity=cash,
            current_equity=cash,
            max_concurrent_shorts=int(self._pf.get("max_concurrent_shorts", 5)),
        )

    def _stream_url(self) -> str:
        streams = "/".join(f"{a.lower()}@kline_{self._interval}" for a in self._assets)
        return f"{_DEMO_WS}?streams={streams}"

    def _current_price(self, asset: str) -> float:
        candles = self._buffer.get(asset)
        return candles[-1].close if candles else 0.0

    def _enter(self, asset: str, side: str, amount: float) -> None:
        price = self._current_price(asset)
        if price <= 0:
            return
        self._positions[asset] = VirtualPosition(asset=asset, side=side,
                                                  entry_price=price, size_usdt=amount)
        log.info("PAPER %s %s @ %.4f (%.2f USDT)", side, asset, price, amount)

    def _exit(self, asset: str) -> None:
        pos = self._positions.pop(asset, None)
        if pos is None or pos.side == "FLAT":
            return
        price = self._current_price(asset)
        raw_pnl = (price - pos.entry_price) / pos.entry_price * pos.size_usdt
        pnl = raw_pnl if pos.side == "LONG" else -raw_pnl
        self._trades.append(PaperTrade(
            asset=asset, side=pos.side,
            entry_price=pos.entry_price, exit_price=price,
            size_usdt=pos.size_usdt, pnl=pnl,
        ))
        self._risk.current_equity += pnl
        log.info("PAPER EXIT %s %s pnl=%.4f equity=%.2f",
                 asset, pos.side, pnl, self._risk.current_equity)

    def _on_closed_candle(self, msg: dict[str, Any]) -> None:
        from Dataframe.Frame import build
        from Strategy.Strategy import evaluate
        import polars as pl

        stream = msg.get("stream", "")
        asset = stream.split("@")[0].upper() + "USDT" if "@" in stream else ""
        if asset not in self._assets:
            return
        if not self._buffer.ingest_ws(asset, msg):
            return
        if not self._buffer.ready(asset, _MIN_BARS):
            return

        ohlcv = pl.DataFrame(self._buffer.to_dicts(asset)).with_columns(
            pl.from_epoch(pl.col("timestamp"), time_unit="ms").alias("timestamp")
        )
        allocs = {
            a: self._risk.current_equity * float(self._pf.get("allocation", {}).get(a, 0.0))
            for a in self._assets
        }
        pos = self._positions.get(asset)
        exposure = {asset: (1.0 if pos and pos.side == "LONG"
                            else -1.0 if pos and pos.side == "SHORT" else 0.0)}
        frame = build(ohlcv)
        decisions = evaluate(frame.filter(pl.col("asset") == asset), asset_exposures=exposure)
        last = decisions.filter(pl.col("asset") == asset).sort("timestamp").tail(1)
        if last.is_empty():
            return

        row = last.row(0, named=True)
        action = row.get("action", "Hold")
        side = row.get("side", "")
        amount = size_trade(self._risk.current_equity, asset, portfolio=self._pf)

        if action == "Entry":
            ex_side = "LONG" if side == "Long" else "SHORT"
            ok, reason = check_entry(self._risk, ex_side, asset, amount)
            if ok:
                self._enter(asset, ex_side, amount)
                on_entry(self._risk, ex_side)
            else:
                log.info("PAPER entry blocked %s: %s", asset, reason)
        elif row.get("exit_required") and asset in self._positions:
            old_side = self._positions[asset].side
            self._exit(asset)
            on_exit(self._risk, old_side)

    async def _listen(self) -> None:
        async with websockets.connect(self._stream_url()) as ws:
            async for raw in ws:
                if not self._running:
                    break
                try:
                    self._on_closed_candle(json.loads(raw))
                except Exception:
                    log.exception("Paper candle error")

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
                log.exception("Paper WS disconnected — reconnecting in %ds", self._reconnect)
                await asyncio.sleep(self._reconnect)

    @property
    def equity(self) -> float:
        return self._risk.current_equity

    @property
    def trades(self) -> list[PaperTrade]:
        return list(self._trades)

    @property
    def positions(self) -> dict[str, VirtualPosition]:
        return dict(self._positions)
