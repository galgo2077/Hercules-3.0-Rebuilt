"""Deterministic, self-contained Hercules strategy-frame construction."""

from __future__ import annotations

import math
import tomllib
from collections.abc import Callable
from pathlib import Path

import numpy as np
import polars as pl

from Dataframe.Compute import rolling_slope

_STRATEGY_TOML = Path(__file__).parent.parent / "SharedData" / "Strategy.toml"

FRAME_COLUMNS = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "asset",
    "direction",
    "short_trend_similarity",
    "final_signal",
    "slope",
)


def _strategy_config() -> dict:
    with _STRATEGY_TOML.open("rb") as handle:
        return tomllib.load(handle)


def _ewma(values: np.ndarray, half_life: int) -> np.ndarray:
    if half_life <= 0:
        raise ValueError("RDMA half-life must be positive")
    alpha = 1.0 - math.exp(math.log(0.5) / half_life)
    result = np.empty_like(values, dtype=np.float64)
    result[0] = values[0]
    for index in range(1, len(values)):
        result[index] = alpha * values[index] + (1.0 - alpha) * result[index - 1]
    return result


def _consecutive(values: list[str]) -> np.ndarray:
    counts = np.ones(len(values), dtype=np.int64)
    for index in range(1, len(values)):
        counts[index] = counts[index - 1] + 1 if values[index] == values[index - 1] else 1
    return counts


def _build_asset(frame: pl.DataFrame, params: dict, conditions: dict) -> pl.DataFrame:
    frame = frame.sort("timestamp")
    close = frame["close"].to_numpy()
    if len(close) == 0:
        return frame

    fast = _ewma(close, int(params.get("rdma_fast_half_life", 25)))
    medium = _ewma(close, int(params.get("rdma_medium_half_life", 100)))
    slow = _ewma(close, int(params.get("rdma_slow_half_life", 250)))
    bullish = str(conditions.get("bullish_direction", "BULLISH"))
    bearish = str(conditions.get("bearish_direction", "BEARISH"))
    sideways = str(conditions.get("sideways_direction", "SIDEWAYS"))
    directions = np.where((fast > medium) & (medium > slow), bullish, np.where((fast < medium) & (medium < slow), bearish, sideways)).tolist()
    runs = _consecutive(directions)

    short_window = max(1, int(params.get("short_trend_window", conditions.get("short_trend_window", 5))))
    bearish_values = np.asarray([direction == bearish for direction in directions], dtype=np.float64)
    similarity = np.empty(len(close), dtype=np.float64)
    for index in range(len(close)):
        start = max(0, index - short_window + 1)
        similarity[index] = bearish_values[start : index + 1].mean()

    minimum_direction = max(1, int(params.get("min_direction_bars", 1)))
    minimum_bearish = max(1, int(params.get("short_entry_minimum_bearish_bars", conditions.get("short_entry_minimum_bearish_bars", 1))))
    signal = np.zeros(len(close), dtype=np.int8)
    for index, direction in enumerate(directions):
        if direction == bullish and runs[index] >= minimum_direction:
            signal[index] = 1
        elif direction == bearish and runs[index] >= max(minimum_direction, minimum_bearish):
            signal[index] = -1

    slope = rolling_slope(slow, max(2, int(params.get("slope_lookback", 6))))
    return frame.with_columns(
        pl.Series("direction", directions, dtype=pl.String),
        pl.Series("short_trend_similarity", similarity, dtype=pl.Float64),
        pl.Series("final_signal", signal, dtype=pl.Int8),
        pl.Series("slope", slope, dtype=pl.Float64),
    )


def _validate(frame: pl.DataFrame) -> None:
    missing = set(FRAME_COLUMNS) - set(frame.columns)
    if missing:
        raise RuntimeError(f"Frame pipeline missing columns: {sorted(missing)}")


def build(
    ohlcv: pl.DataFrame,
    progress: Callable[[str], None] | None = None,
    *,
    n_workers: int | None = None,
    strategy_config: dict | None = None,
) -> pl.DataFrame:
    """Build signals from OHLCV without relying on another repository."""
    del n_workers
    if "timestamp" not in ohlcv.columns and "open_time" in ohlcv.columns:
        ohlcv = ohlcv.rename({"open_time": "timestamp"})
    required = {"timestamp", "open", "high", "low", "close", "volume", "asset"}
    missing = required - set(ohlcv.columns)
    if missing:
        raise ValueError(f"OHLCV missing columns: {sorted(missing)}")
    if ohlcv.is_empty():
        return pl.DataFrame(schema={column: pl.Null for column in FRAME_COLUMNS})

    cfg = strategy_config or _strategy_config()
    conditions = cfg.get("conditions", {})
    parts: list[pl.DataFrame] = []
    for asset in ohlcv["asset"].unique(maintain_order=True).to_list():
        params = {**conditions, **cfg.get("assets", {}).get(asset, {})}
        parts.append(_build_asset(ohlcv.filter(pl.col("asset") == asset), params, conditions))
        if progress is not None:
            progress(asset)
    frame = pl.concat(parts).sort("timestamp", "asset")
    _validate(frame)
    return frame.select(*FRAME_COLUMNS)
