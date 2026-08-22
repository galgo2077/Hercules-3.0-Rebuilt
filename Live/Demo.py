"""Binance Demo (testnet) execution engine — candle-driven live loop."""

from __future__ import annotations

import asyncio
import json
import logging
import tomllib
from pathlib import Path
from typing import Any

import websockets

from Dataframe.CandleBuffer import CandleBuffer
from Live._client import BinanceClient
from Live.Positions import PositionTracker
from Live.Risk import RiskState, check_entry, eviction_priority, on_entry, on_exit

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]
_SHARED = _ROOT / "SharedData"

_DEMO_REST = "https://testnet.binancefuture.com"
_DEMO_WS = "wss://stream.binancefuture.com/stream"
_MIN_BARS = 200


def _load_config() -> tuple[dict, dict]:
    with (_SHARED / "Live.toml").open("rb") as f:
        live = tomllib.load(f)
    with (_SHARED / "Portfolio.toml").open("rb") as f:
        pf = tomllib.load(f)
    return live, pf


def _stream_url(assets: list[str], interval: str) -> str:
    streams = "/".join(f"{a.lower()}@kline_{interval}" for a in assets)
    return f"{_DEMO_WS}?streams={streams}"


class DemoEngine:
    """Runs strategy → risk → execute loop against Binance demo futures.

    api_key / api_secret: Binance credentials for this account.
                          Falls back to BINANCE_API_KEY/SECRET env vars if omitted.
    label: identifies this account in log output (e.g. "demo-alice", "real-fund1").
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
        label: str = "demo",
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._label = label
        self._live, self._pf = _load_config()
        self._assets: list[str] = list(self._pf.get("allocation", {}).keys())
        self._interval: str = self._live.get("interval", "1h")
        self._reconnect: int = int(self._live.get("reconnect_delay_s", 5))
        self._rest_url: str = self._live.get("binance_base_url", _DEMO_REST)
        self._tracker = PositionTracker()
        self._buffer = CandleBuffer(capacity=600)
        self._running = False
        # per-asset lock: prevents concurrent mutations of shared state per asset
        self._asset_locks: dict[str, asyncio.Lock] = {a: asyncio.Lock() for a in self._assets}
        cash = float(self._pf.get("initial_cash", 100.0))
        self._risk = RiskState(
            initial_equity=cash,
            current_equity=cash,
            max_concurrent_shorts=int(self._pf.get("max_concurrent_shorts", 5)),
        )

    def _client(self) -> BinanceClient:
        return BinanceClient(self._rest_url, api_key=self._api_key, api_secret=self._api_secret)

    def _allocations(self) -> dict[str, float]:
        weights = self._pf.get("allocation", {})
        cash = self._risk.current_equity
        return {a: cash * float(weights.get(a, 0.0)) for a in self._assets}

    def _dispatch_candle(self, client: BinanceClient, msg: dict[str, Any]) -> None:
        """Parse message and schedule per-asset processing as a concurrent task."""
        stream = msg.get("stream", "")
        asset = stream.split("@")[0].upper() + "USDT" if "@" in stream else ""
        if asset not in self._assets:
            return
        if not self._buffer.ingest_ws(asset, msg):
            return  # not closed candle
        if not self._buffer.ready(asset, _MIN_BARS):
            return
        asyncio.ensure_future(self._process_asset(client, asset))

    async def _process_asset(self, client: BinanceClient, asset: str) -> None:
        """Build frame + evaluate strategy for one asset, then execute. Runs concurrently."""
        import polars as pl
        from Dataframe.Frame import build
        from Strategy.Strategy import evaluate

        rows = self._buffer.to_dicts(asset)
        ohlcv = pl.DataFrame(rows).with_columns(
            pl.from_epoch(pl.col("timestamp"), time_unit="ms").alias("timestamp")
        )
        # build + evaluate are CPU-heavy (call Rust/original repo); run in thread to not block WS
        frame = await asyncio.to_thread(build, ohlcv)
        allocs = self._allocations()
        exposures = self._tracker.as_exposure_dict(allocs)
        decisions = await asyncio.to_thread(
            evaluate, frame.filter(pl.col("asset") == asset), asset_exposures=exposures
        )

        last = decisions.filter(pl.col("asset") == asset).sort("timestamp").tail(1)
        if last.is_empty():
            return

        async with self._asset_locks[asset]:
            self._execute(client, last.row(0, named=True), allocs)

    def _execute(self, client: BinanceClient, row: dict, allocs: dict[str, float]) -> None:
        from Live.Orders import Long, Short
        from Strategy.Strategy import asset_risk_params

        asset = row["asset"]
        action = row.get("action", "Hold")
        side = row.get("side", "")
        risk = asset_risk_params(asset, portfolio_toml=_SHARED / "Portfolio.toml")
        leverage = int(risk["leverage"] or 1)
        weight = float(self._pf.get("allocation", {}).get(asset, 0.0))
        amount = self._risk.current_equity * weight * (risk["trade_size_pct"] or 0.30) * leverage

        if action == "Entry":
            ex_side = "LONG" if side == "Long" else "SHORT"
            current = self._tracker.get(asset)
            if ex_side == "SHORT" and current.side == "LONG":
                # LONGs have no exit — reversal signal suppressed, long continues
                log.debug("suppress SHORT reversal — LONG active on %s", asset)
                return
            allowed, reason = check_entry(self._risk, ex_side, asset, amount)
            if not allowed:
                log.warning("entry blocked %s %s: %s", asset, ex_side, reason)
                return
            other_pos = {a: p for a, p in self._tracker.all().items() if not p.is_flat and a != asset}
            deployed = sum(p.size_usdt for p in other_pos.values())
            free = self._risk.current_equity - deployed
            if amount > free and other_pos:
                victim = eviction_priority(other_pos)[0]
                victim_side = other_pos[victim].side
                log.info("evict %s (%s) → free capital for %s %s", victim, victim_side, ex_side, asset)
                if victim_side == "LONG":
                    Long.exit(client, victim)
                else:
                    Short.exit(client, victim)
                on_exit(self._risk, victim_side)
            if side == "Long":
                log.info("DEMO ENTRY LONG %s %.2f USDT lev=%d", asset, amount, leverage)
                Long.enter(client, asset, amount, leverage)
            else:
                log.info("DEMO ENTRY SHORT %s %.2f USDT lev=%d sl=%.3f tp=%.3f",
                         asset, amount, leverage, risk["stop_loss_pct"] or 0, risk["take_profit_pct"] or 0)
                Short.enter(client, asset, amount, leverage,
                            stop_loss_pct=risk["stop_loss_pct"],
                            take_profit_pct=risk["take_profit_pct"])
            on_entry(self._risk, ex_side)

        elif row.get("exit_required"):
            pos = self._tracker.get(asset)
            if pos.side == "LONG":
                log.info("DEMO EXIT LONG %s", asset)
                Long.exit(client, asset)
                on_exit(self._risk, "LONG")
            elif pos.side == "SHORT":
                log.info("DEMO EXIT SHORT %s", asset)
                Short.exit(client, asset)
                on_exit(self._risk, "SHORT")

    async def _listen(self) -> None:
        url = _stream_url(self._assets, self._interval)
        with self._client() as client:
            client.ensure_hedge_mode()  # must run before any order; raises if it fails
            self._tracker.fetch(client)
            async with websockets.connect(url) as ws:
                async for raw in ws:
                    if not self._running:
                        break
                    try:
                        self._dispatch_candle(client, json.loads(raw))
                    except Exception:
                        log.exception("[%s] candle dispatch error", self._label)

    def start(self) -> None:
        self._running = True
        asyncio.run(self._run_loop())

    def stop(self) -> None:
        self._running = False

    def _warmup(self) -> None:
        from Dataframe.OhlcvCache import fetch_warmup
        log.info("[%s] warmup: fetching %d bars for %s interval=%s", self._label, self._buffer.capacity, self._assets, self._interval)
        df = fetch_warmup(self._assets, self._interval, self._buffer.capacity)
        for row in df.iter_rows(named=True):
            ts_ms = int(row["timestamp"].timestamp() * 1000)
            self._buffer.ingest(row["asset"], {"t": ts_ms, "o": row["open"], "h": row["high"], "l": row["low"], "c": row["close"], "v": row["volume"]}, is_closed=True)
        log.info("[%s] warmup done: %s", self._label, {a: len(self._buffer.get(a)) for a in self._assets})

    async def _run_loop(self) -> None:
        self._warmup()
        while self._running:
            try:
                await self._listen()
            except Exception:
                log.exception("Demo WS disconnected — reconnecting in %ds", self._reconnect)
                await asyncio.sleep(self._reconnect)
