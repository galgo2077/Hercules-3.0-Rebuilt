"""Binance Demo (testnet) execution engine — candle-driven live loop."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import tomllib
from pathlib import Path
from typing import Any

import websockets

from Dataframe.CandleBuffer import CandleBuffer
from Live._client import BinanceClient
from Live.Execution import stream_asset
from Live.Positions import PositionTracker
from Live.Risk import RiskState, check_entry, size_trade, update_equity

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
        account_id: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._label = label
        self._account_id = account_id
        self._live, self._pf = _load_config()
        self._assets: list[str] = list(self._pf.get("allocation", {}).keys())
        self._interval: str = self._live.get("interval", "1h")
        self._reconnect: int = int(self._live.get("reconnect_delay_s", 5))
        self._rest_url = _DEMO_REST
        self._ws_url = _DEMO_WS
        self._tracker = PositionTracker()
        self._buffer = CandleBuffer(capacity=600)
        self._running = False
        self._tasks: set[asyncio.Task[None]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._websocket: Any = None
        # per-asset lock: prevents concurrent mutations of shared state per asset
        self._asset_locks: dict[str, asyncio.Lock] = {a: asyncio.Lock() for a in self._assets}
        cash = float(self._pf.get("initial_cash", 100.0))
        self._risk = RiskState(
            initial_equity=cash,
            current_equity=cash,
            max_concurrent_shorts=int(self._pf.get("max_concurrent_shorts", 5)),
        )
        self._equity_initialized = False

    def _client(self) -> BinanceClient:
        return BinanceClient(self._rest_url, api_key=self._api_key, api_secret=self._api_secret)

    def _allocations(self) -> dict[str, float]:
        weights = self._pf.get("allocation", {})
        cash = self._risk.current_equity
        return {a: cash * float(weights.get(a, 0.0)) for a in self._assets}

    def _refresh(self, client: BinanceClient) -> None:
        account = client.get("/fapi/v2/account")
        raw_equity = account.get("totalMarginBalance") or account.get("totalWalletBalance")
        if raw_equity is None:
            raise RuntimeError("exchange account response missing wallet equity")
        equity = float(raw_equity)
        available = float(account.get("availableBalance", equity))
        if not math.isfinite(equity) or equity <= 0 or not math.isfinite(available) or available < 0:
            raise RuntimeError("exchange returned non-positive wallet equity")
        self._tracker.fetch(client)
        update_equity(self._risk, equity, available)
        if not self._equity_initialized:
            self._risk.initial_equity = equity
            self._equity_initialized = True
        self._risk.open_shorts = sum(position.side == "SHORT" and not position.is_flat for position in self._tracker.all().values())
        if self._account_id is not None:
            from Storage.Repos import persist_snapshot

            positions = []
            for asset in self._assets:
                for side in ("LONG", "SHORT"):
                    position = self._tracker.get(asset, side)
                    positions.append(
                        {
                            "asset": asset,
                            "side": side,
                            "size_usdt": 0.0 if position.is_flat else position.size_usdt,
                            "entry_price": None if position.is_flat else position.entry_price,
                        }
                    )
            persist_snapshot(self._account_id, equity, positions)

    def _dispatch_candle(self, client: BinanceClient, msg: dict[str, Any]) -> None:
        """Parse message and schedule per-asset processing as a concurrent task."""
        stream = msg.get("stream", "")
        asset = stream_asset(stream, self._assets)
        if asset is None:
            return
        if not self._buffer.ingest_ws(asset, msg):
            return  # not closed candle
        if not self._buffer.ready(asset, _MIN_BARS):
            return
        task = asyncio.create_task(self._process_asset(client, asset))
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("[%s] asset processing failed", self._label, exc_info=task.exception())

    async def _process_asset(self, client: BinanceClient, asset: str) -> None:
        """Build frame + evaluate strategy for one asset, then execute. Runs concurrently."""
        import polars as pl

        from Dataframe.Frame import build
        from Strategy.Strategy import decide

        rows = self._buffer.to_dicts(asset)
        ohlcv = pl.DataFrame(rows).with_columns(pl.from_epoch(pl.col("timestamp"), time_unit="ms").alias("timestamp"))
        # Frame/strategy work runs off the WebSocket event loop.
        frame = await asyncio.to_thread(build, ohlcv)
        async with self._asset_locks[asset]:
            await asyncio.to_thread(self._refresh, client)
            allocs = self._allocations()
            last = frame.filter(pl.col("asset") == asset).sort("timestamp").tail(1)
            if last.is_empty():
                return
            row = last.row(0, named=True)
            decision = await asyncio.to_thread(decide, row, self._tracker.exposure(asset, allocs[asset]))
            await asyncio.to_thread(self._execute, client, {**row, **decision})

    def _execute(self, client: BinanceClient, row: dict) -> None:
        from Live.Orders import Long, Short
        from Strategy.Strategy import asset_risk_params

        asset = row["asset"]
        action = row.get("action", "Hold")
        side = row.get("side", "")
        risk = asset_risk_params(asset, portfolio_toml=_SHARED / "Portfolio.toml")
        leverage = int(risk["leverage"] or 1)
        self._refresh(client)
        amount = size_trade(self._risk.current_equity, asset, portfolio=self._pf, risk=risk)

        if action == "Entry":
            ex_side = "LONG" if side == "Long" else "SHORT"
            if not self._tracker.get(asset, ex_side).is_flat:
                return
            old_side = "SHORT" if ex_side == "LONG" else "LONG"
            if not self._tracker.get(asset, old_side).is_flat:
                log.info("DEMO reversal %s %s -> %s", asset, old_side, ex_side)
                if old_side == "LONG":
                    Long.exit(client, asset)
                else:
                    Short.exit(client, asset)
                self._refresh(client)
                if not self._tracker.get(asset, old_side).is_flat:
                    raise RuntimeError(f"exchange did not confirm {old_side} close for {asset}")
            allowed, reason = check_entry(self._risk, ex_side, asset, amount, amount / leverage)
            if not allowed:
                log.warning("entry blocked %s %s: %s", asset, ex_side, reason)
                return
            if side == "Long":
                log.info("DEMO ENTRY LONG %s %.2f USDT lev=%d", asset, amount, leverage)
                Long.enter(client, asset, amount, leverage, stop_loss_pct=risk["stop_loss_pct"], take_profit_pct=risk["take_profit_pct"])
            else:
                log.info("DEMO ENTRY SHORT %s %.2f USDT lev=%d sl=%.3f tp=%.3f", asset, amount, leverage, risk["stop_loss_pct"] or 0, risk["take_profit_pct"] or 0)
                Short.enter(client, asset, amount, leverage, stop_loss_pct=risk["stop_loss_pct"], take_profit_pct=risk["take_profit_pct"])
            self._refresh(client)
            if self._tracker.get(asset, ex_side).is_flat:
                raise RuntimeError(f"exchange did not confirm {ex_side} entry for {asset}")

        elif row.get("exit_required"):
            pos = self._tracker.get(asset)
            if pos.side == "LONG":
                log.info("DEMO EXIT LONG %s", asset)
                Long.exit(client, asset)
            elif pos.side == "SHORT":
                log.info("DEMO EXIT SHORT %s", asset)
                Short.exit(client, asset)
            self._refresh(client)

    async def _listen(self) -> None:
        url = _stream_url(self._assets, self._interval).replace(_DEMO_WS, self._ws_url, 1)
        self._loop = asyncio.get_running_loop()
        with self._client() as client:
            client.ensure_hedge_mode()  # must run before any order; raises if it fails
            self._refresh(client)
            try:
                async with websockets.connect(url) as ws:
                    self._websocket = ws
                    try:
                        async for raw in ws:
                            if not self._running:
                                break
                            try:
                                self._dispatch_candle(client, json.loads(raw))
                            except Exception:
                                log.exception("[%s] candle dispatch error", self._label)
                    finally:
                        self._websocket = None
            finally:
                if self._tasks:
                    await asyncio.gather(*self._tasks, return_exceptions=True)

    def start(self) -> None:
        self._running = True
        asyncio.run(self._run_loop())

    def stop(self) -> None:
        self._running = False
        if self._loop is not None and self._websocket is not None:
            asyncio.run_coroutine_threadsafe(self._websocket.close(), self._loop)

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
