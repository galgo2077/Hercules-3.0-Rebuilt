"""Gap detection and fill for CandleBuffer after WebSocket reconnect."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from Dataframe.Binance import INTERVAL_MS, fetch_historical
from Dataframe.CandleBuffer import CandleBuffer


def detect_gap(
    buffer: CandleBuffer,
    asset: str,
    interval_ms: int,
) -> tuple[int, int] | None:
    """Return (gap_start_ms, gap_end_ms) if last candle older than 2*interval_ms, else None."""
    candles = buffer.get(asset)
    if not candles:
        return None
    last_ms = candles[-1].timestamp_ms
    now_ms = int(time.time() * 1000)
    if now_ms - last_ms > 2 * interval_ms:
        return last_ms + interval_ms, now_ms
    return None


def fill_gap(
    buffer: CandleBuffer,
    asset: str,
    gap_start_ms: int,
    gap_end_ms: int,
    interval: str = "1h",
) -> int:
    """Fetch missing candles via Binance REST and ingest into buffer. Returns count filled."""
    start_iso = datetime.fromtimestamp(gap_start_ms / 1000, tz=timezone.utc).isoformat()
    end_iso = datetime.fromtimestamp(gap_end_ms / 1000, tz=timezone.utc).isoformat()

    df = fetch_historical([asset], start_iso, end_iso, interval=interval)
    if df.is_empty():
        return 0

    filled = 0
    for row in df.iter_rows(named=True):
        ts = row["timestamp"]
        ts_ms = int(ts.timestamp() * 1000)
        kline = {
            "t": ts_ms,
            "o": row["open"],
            "h": row["high"],
            "l": row["low"],
            "c": row["close"],
            "v": row["volume"],
        }
        if buffer.ingest(asset, kline, is_closed=True):
            filled += 1
    return filled


def recover(
    buffer: CandleBuffer,
    assets: list[str],
    interval: str = "1h",
) -> dict[str, int]:
    """Run detect_gap + fill_gap for each asset. Returns {asset: bars_filled}."""
    interval_ms = INTERVAL_MS[interval]
    result: dict[str, int] = {}
    for asset in assets:
        gap = detect_gap(buffer, asset, interval_ms)
        if gap is None:
            result[asset] = 0
        else:
            gap_start_ms, gap_end_ms = gap
            result[asset] = fill_gap(buffer, asset, gap_start_ms, gap_end_ms, interval)
    return result
