"""Binance Spot REST OHLCV fetcher."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from datetime import time as dtime
from threading import Lock
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import polars as pl

KLINES_URL = "https://api.binance.com/api/v3/klines"
INTERVAL_MS: dict[str, int] = {
    "1s": 1_000,
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
    "1M": 2_592_000_000,
}
_KLINE_COLS = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "unused",
)
_FLOAT_COLS = ("open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base_volume", "taker_buy_quote_volume")

OHLCV_SCHEMA: dict[str, object] = {
    "timestamp": pl.Datetime("ms", "UTC"),
    "asset": pl.String,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
}


class BinanceError(RuntimeError):
    pass


class _RateLimiter:
    def __init__(self, requests_per_minute: int = 50) -> None:
        self._interval = 60.0 / max(1, requests_per_minute)
        self._next: float | None = None
        self._lock = Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = now if self._next is None else max(now, self._next)
            self._next = slot + self._interval
            delay = slot - now
        if delay > 0:
            time.sleep(delay)


def _request(query: str) -> list[list[Any]]:
    try:
        with urlopen(f"{KLINES_URL}?{query}", timeout=30) as r:  # noqa: S310 -- constant HTTPS endpoint
            payload = json.load(r)
    except HTTPError as e:
        raise BinanceError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}") from e
    except (URLError, TimeoutError, json.JSONDecodeError) as e:
        raise BinanceError(f"request failed: {e}") from e
    if not isinstance(payload, list):
        raise BinanceError(f"unexpected response: {payload!r}")
    return payload


def _fetch_klines(
    asset: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    limiter: _RateLimiter,
    progress: Callable[[int], None] | None,
) -> pl.DataFrame:
    rows: list[list[Any]] = []
    cursor = start_ms
    while cursor <= end_ms:
        params = {"symbol": asset, "interval": interval, "startTime": cursor, "endTime": end_ms, "limit": 1000}
        limiter.wait()
        page = _request(urlencode(params))
        if not page:
            break
        rows.extend(page)
        if progress:
            progress(len(rows))
        next_cursor = int(page[-1][0]) + 1
        if len(page) < 1000 or next_cursor <= cursor:
            break
        cursor = next_cursor

    if not rows:
        return pl.DataFrame(
            schema={
                "asset": pl.String,
                "timestamp": pl.Datetime("ms", "UTC"),
                **{c: pl.Float64 for c in ("open", "high", "low", "close", "volume")},
            }
        )

    frame = (
        pl.DataFrame(rows, schema=_KLINE_COLS, orient="row")
        .drop("unused", "close_time", "quote_volume", "trades", "taker_buy_base_volume", "taker_buy_quote_volume")
        .with_columns(
            pl.lit(asset).alias("asset"),
            pl.col("timestamp").cast(pl.Datetime("ms", "UTC")),
            pl.col("open", "high", "low", "close", "volume").cast(pl.Float64),
        )
        .select("asset", "timestamp", "open", "high", "low", "close", "volume")
    )
    return frame


def _to_ms(value: str | date | datetime, *, end_of_day: bool) -> int:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as e:
            raise ValueError(f"invalid ISO date: {value}") from e
    if isinstance(value, datetime):
        moment = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    else:
        moment = datetime.combine(value, dtime.max if end_of_day else dtime.min, timezone.utc)
    return int(moment.timestamp() * 1000)


def fetch_historical(
    assets: str | Sequence[str],
    start: str | date | datetime,
    end: str | date | datetime | None = None,
    *,
    interval: str = "1h",
    requests_per_minute: int = 50,
    progress: Callable[[str, int], None] | None = None,
) -> pl.DataFrame:
    if interval not in INTERVAL_MS:
        raise ValueError(f"unsupported interval: {interval}")
    symbols = [assets] if isinstance(assets, str) else list(assets)
    symbols = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    if not symbols:
        raise ValueError("assets must not be empty")

    start_ms = _to_ms(start, end_of_day=False)
    end_ms = _to_ms(end or datetime.now(timezone.utc), end_of_day=True)
    if start_ms > end_ms:
        raise ValueError("start must not be after end")

    limiter = _RateLimiter(requests_per_minute)

    def fetch(symbol: str) -> pl.DataFrame:
        callback = cast(Callable[[str, int], None], progress) if progress else None

        def report(count: int) -> None:
            if callback is not None:
                callback(symbol, count)

        return _fetch_klines(
            symbol,
            interval,
            start_ms,
            end_ms,
            limiter,
            report if callback else None,
        )

    with ThreadPoolExecutor(max_workers=len(symbols), thread_name_prefix="binance") as pool:
        frames = list(pool.map(fetch, symbols))

    return pl.concat(frames).sort("timestamp", "asset")
