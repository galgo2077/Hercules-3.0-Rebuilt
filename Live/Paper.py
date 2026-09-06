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
from Live.Execution import stream_asset
from Live.Risk import RiskState, check_entry, on_entry, on_exit, size_trade

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]
_DEMO_WS = "wss://stream.binancefuture.com/stream"
_MIN_BARS = 200


def _load_config() -> tuple[dict, dict]:
    with (_ROOT / "SharedData" / "Live.toml").open("rb") as f:
        live = tomllib.load(f)
    with (_ROOT / "SharedData" / "Portfolio.toml").open("rb") as f:
        pf = tomllib.load(f)
    return live, pf


@dataclass
class VirtualPosition:
    asset: str
    side: str  # LONG | SHORT | FLAT
    entry_price: float = 0.0
    size_usdt: float = 0.0
    open_time: float = field(default_factory=time.time)
    stop_loss_price: float | None = None
    take_profit_price: float | None = None


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

    def __init__(self, *, account_id: str | None = None) -> None:
        self._live, self._pf = _load_config()
        self._assets: list[str] = list(self._pf.get("allocation", {}).keys())
        self._interval: str = self._live.get("interval", "1h")
        self._reconnect: int = int(self._live.get("reconnect_delay_s", 5))
        self._buffer = CandleBuffer(capacity=600)
        self._positions: dict[str, VirtualPosition] = {}
        self._trades: list[PaperTrade] = []
        self._running = False
        self._account_id = account_id
        with (_ROOT / "SharedData" / "Backtest.toml").open("rb") as handle:
            cash = float(tomllib.load(handle)["capital"]["initial_cash"])
        self._risk = RiskState(
            initial_equity=cash,
            current_equity=cash,
            max_concurrent_shorts=int(self._pf.get("max_concurrent_shorts", 5)),
        )

    def _persist(self) -> None:
        if self._account_id is None:
            return
        from Storage.Repos import persist_snapshot

        positions = []
        for asset in self._assets:
            position = self._positions.get(asset)
            for side in ("LONG", "SHORT"):
                positions.append(
                    {
                        "asset": asset,
                        "side": side,
                        "size_usdt": position.size_usdt if position is not None and position.side == side else 0.0,
                        "entry_price": position.entry_price if position is not None and position.side == side else None,
                    }
                )
        persist_snapshot(self._account_id, self._risk.current_equity, positions)

    def _stream_url(self) -> str:
        streams = "/".join(f"{a.lower()}@kline_{self._interval}" for a in self._assets)
        return f"{_DEMO_WS}?streams={streams}"

    def _current_price(self, asset: str) -> float:
        candles = self._buffer.get(asset)
        return candles[-1].close if candles else 0.0

    def _enter(
        self,
        asset: str,
        side: str,
        amount: float,
        *,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
    ) -> None:
        price = self._current_price(asset)
        if price <= 0:
            raise RuntimeError(f"no valid market price for {asset}")
        if stop_loss_pct is None and take_profit_pct is None:
            raise ValueError("at least one protective exit is required")
        sl = round(price * (1.0 - stop_loss_pct if side == "LONG" else 1.0 + stop_loss_pct), 8) if stop_loss_pct is not None else None
        tp = round(price * (1.0 + take_profit_pct if side == "LONG" else 1.0 - take_profit_pct), 8) if take_profit_pct is not None else None
        self._positions[asset] = VirtualPosition(
            asset=asset,
            side=side,
            entry_price=price,
            size_usdt=amount,
            stop_loss_price=sl,
            take_profit_price=tp,
        )
        self._persist()
        log.info("PAPER %s %s @ %.4f (%.2f USDT) SL=%s TP=%s", side, asset, price, amount, f"{sl:.4f}" if sl else "none", f"{tp:.4f}" if tp else "none")

    def _exit(self, asset: str) -> None:
        pos = self._positions.pop(asset, None)
        if pos is None or pos.side == "FLAT":
            return
        price = self._current_price(asset)
        raw_pnl = (price - pos.entry_price) / pos.entry_price * pos.size_usdt
        pnl = raw_pnl if pos.side == "LONG" else -raw_pnl
        self._trades.append(
            PaperTrade(
                asset=asset,
                side=pos.side,
                entry_price=pos.entry_price,
                exit_price=price,
                size_usdt=pos.size_usdt,
                pnl=pnl,
            )
        )
        self._risk.current_equity += pnl
        self._persist()
        log.info("PAPER EXIT %s %s pnl=%.4f equity=%.2f", asset, pos.side, pnl, self._risk.current_equity)

    def _on_closed_candle(self, msg: dict[str, Any]) -> None:
        import polars as pl

        from Dataframe.Frame import build
        from Strategy.Strategy import asset_risk_params, decide

        stream = msg.get("stream", "")
        asset = stream_asset(stream, self._assets)
        if asset is None:
            return
        if not self._buffer.ingest_ws(asset, msg):
            return
        if not self._buffer.ready(asset, _MIN_BARS):
            return

        ohlcv = pl.DataFrame(self._buffer.to_dicts(asset)).with_columns(pl.from_epoch(pl.col("timestamp"), time_unit="ms").alias("timestamp"))

        # Apply protection before evaluating a new target. If both levels were
        # crossed in one candle, the stop wins (fail-conservative ordering).
        pos = self._positions.get(asset)
        if pos:
            candle = ohlcv.tail(1)
            candle_high = float(candle["high"][0])
            candle_low = float(candle["low"][0])
            stop_hit = pos.stop_loss_price is not None and (candle_low <= pos.stop_loss_price if pos.side == "LONG" else candle_high >= pos.stop_loss_price)
            take_hit = pos.take_profit_price is not None and (candle_high >= pos.take_profit_price if pos.side == "LONG" else candle_low <= pos.take_profit_price)
            if stop_hit:
                log.info("PAPER SL hit %s sl=%.4f", asset, pos.stop_loss_price)
                self._exit(asset)
                on_exit(self._risk, pos.side)
                return
            if take_hit:
                log.info("PAPER TP hit %s tp=%.4f", asset, pos.take_profit_price)
                self._exit(asset)
                on_exit(self._risk, pos.side)
                return

        pos = self._positions.get(asset)
        exposure = {asset: (1.0 if pos and pos.side == "LONG" else -1.0 if pos and pos.side == "SHORT" else 0.0)}
        frame = build(ohlcv)
        last = frame.filter(pl.col("asset") == asset).sort("timestamp").tail(1)
        if last.is_empty():
            return

        frame_row = last.row(0, named=True)
        row = {**frame_row, **decide(frame_row, exposure[asset])}
        action = row.get("action", "Hold")
        side = row.get("side", "")
        risk = asset_risk_params(asset)
        amount = size_trade(self._risk.current_equity, asset, portfolio=self._pf, risk=risk)

        if action == "Entry":
            ex_side = "LONG" if side == "Long" else "SHORT"
            current = self._positions.get(asset)
            if current and current.side != ex_side:
                self._exit(asset)
                on_exit(self._risk, current.side)
            deployed_margin = sum(position.size_usdt / float(asset_risk_params(position.asset)["leverage"] or 1) for position in self._positions.values())
            self._risk.available_equity = self._risk.current_equity - deployed_margin
            leverage = float(risk["leverage"] or 1)
            ok, reason = check_entry(self._risk, ex_side, asset, amount, amount / leverage)
            if not ok:
                log.info("PAPER entry blocked %s: %s", asset, reason)
            else:
                self._enter(asset, ex_side, amount, stop_loss_pct=risk["stop_loss_pct"], take_profit_pct=risk["take_profit_pct"])
                on_entry(self._risk, ex_side)
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
                    await asyncio.to_thread(self._on_closed_candle, json.loads(raw))
                except Exception:
                    log.exception("Paper candle error")

    def start(self) -> None:
        self._running = True
        asyncio.run(self._run_loop())

    def stop(self) -> None:
        self._running = False

    def _warmup(self) -> None:
        from Dataframe.OhlcvCache import fetch_warmup

        log.info("Warmup: fetching %d bars for %s interval=%s", self._buffer.capacity, self._assets, self._interval)
        df = fetch_warmup(self._assets, self._interval, self._buffer.capacity)
        for row in df.iter_rows(named=True):
            ts_ms = int(row["timestamp"].timestamp() * 1000)
            self._buffer.ingest(row["asset"], {"t": ts_ms, "o": row["open"], "h": row["high"], "l": row["low"], "c": row["close"], "v": row["volume"]}, is_closed=True)
        log.info("Warmup done: %s", {a: len(self._buffer.get(a)) for a in self._assets})

    async def _run_loop(self) -> None:
        self._warmup()
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
