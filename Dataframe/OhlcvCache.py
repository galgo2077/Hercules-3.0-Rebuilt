"""Disk-backed OHLCV cache for live warmup — parquet, keyed by assets+interval, 1h TTL."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from Dataframe.Binance import INTERVAL_MS, fetch_historical

_DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "ohlcv"


def _warmup_key(assets: list[str], interval: str) -> str:
    payload = json.dumps({"assets": sorted(assets), "interval": interval}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def fetch_warmup(
    assets: list[str],
    interval: str,
    n_bars: int,
    *,
    cache_dir: Path = _DEFAULT_CACHE_DIR,
    ttl_seconds: int = 3600,
    progress=None,
) -> pl.DataFrame:
    """Fetch last n_bars of OHLCV for assets/interval, using disk cache.

    Cache keyed by (sorted assets, interval). Stale after ttl_seconds.
    Returns polars DataFrame with columns: asset, timestamp, open, high, low, close, volume.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"warmup_{_warmup_key(assets, interval)}.parquet"

    if path.exists() and (time.time() - path.stat().st_mtime) < ttl_seconds:
        return pl.read_parquet(path)

    interval_ms = INTERVAL_MS[interval]
    end = datetime.now(timezone.utc)
    start = end - timedelta(milliseconds=interval_ms * n_bars)

    df = fetch_historical(assets, start, end, interval=interval, progress=progress)
    df.write_parquet(path)
    return df
