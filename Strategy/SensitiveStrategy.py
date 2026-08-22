"""Synthetic frame generator for exhaustive parity testing — fires signal on every candle."""

from __future__ import annotations

import datetime

import polars as pl

_BASE_TS = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)


def make_sensitive_frame(asset: str, n_candles: int, start_price: float = 100.0) -> pl.DataFrame:
    """Return a synthetic Hercules frame where final_signal fires on every candle.

    Alternates long (1) / short (-1) per candle.
    Slope sign matches signal to satisfy require_slope_confirmation=True.
    """
    timestamps = [_BASE_TS + datetime.timedelta(hours=i) for i in range(n_candles)]
    signals = [1 if i % 2 == 0 else -1 for i in range(n_candles)]
    slopes = [0.01 if s == 1 else -0.01 for s in signals]
    directions = ["BULLISH" if s == 1 else "BEARISH" for s in signals]
    opens = [start_price + i * 0.1 for i in range(n_candles)]
    closes = [o + 0.05 for o in opens]
    highs = [o + 0.15 for o in opens]
    lows = [o - 0.05 for o in opens]

    return pl.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [1000.0] * n_candles,
        "asset": [asset] * n_candles,
        "direction": directions,
        "short_trend_similarity": [0.6] * n_candles,
        "final_signal": signals,
        "slope": slopes,
    })
