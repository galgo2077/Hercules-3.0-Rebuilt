"""Hercules Frame pipeline — delegates to Strategy.getData via original repo bridge."""

from __future__ import annotations

import os
import sys
import threading
import tomllib
from collections.abc import Callable
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import polars as pl

_ROOT = Path(__file__).resolve().parents[1]
_ORIGINAL_REPO = Path(
    os.environ.get("HERCULES_ORIGINAL_ROOT", "/home/void/Documents/Hercules 3.0")
).expanduser()
_STRATEGY_TOML = Path(__file__).parent.parent / "SharedData" / "Strategy.toml"
_IMPORT_LOCK = threading.RLock()

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

_ALL_CONDITION_FIELDS = (
    "minimum_volatility_regime",
    "long_entry_minimum_candles",
    "short_trend_window",
    "short_entry_minimum_bearish_bars",
    "require_slope_confirmation",
    "bullish_direction",
    "bearish_direction",
    "sideways_direction",
    "buy_indicator_signal",
    "sell_indicator_signal",
)

_SIGNAL_TOML_KEYS = {
    "signal_minimum_overall_confidence": "thresholds.minimum_overall_confidence",
    "signal_minimum_signal_score": "thresholds.minimum_signal_score",
}


def _build_config() -> dict:
    with _STRATEGY_TOML.open("rb") as f:
        cfg = tomllib.load(f)

    global_conditions = cfg.get("conditions", {})
    asset_params = cfg.get("assets", {})

    base = {
        "minimum_volatility_regime": global_conditions.get("minimum_volatility_regime", 1),
        "long_entry_minimum_candles": global_conditions.get("long_entry_minimum_candles", 0),
        "short_trend_window": global_conditions.get("short_trend_window", 5),
        "short_entry_minimum_bearish_bars": global_conditions.get("short_entry_minimum_bearish_bars", 0),
        "require_slope_confirmation": global_conditions.get("require_slope_confirmation", True),
        "bullish_direction": global_conditions.get("bullish_direction", "BULLISH"),
        "bearish_direction": global_conditions.get("bearish_direction", "BEARISH"),
        "sideways_direction": global_conditions.get("sideways_direction", "SIDEWAYS"),
        "buy_indicator_signal": global_conditions.get("buy_indicator_signal", "buy"),
        "sell_indicator_signal": global_conditions.get("sell_indicator_signal", "sell"),
    }

    known_assets = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    strategy_by_asset: dict = {}
    indicator_by_asset: dict = {}

    for asset in known_assets:
        params = asset_params.get(asset, {})
        conditions = dict(base)
        for field in _ALL_CONDITION_FIELDS:
            if field in params:
                conditions[field] = params[field]
        strategy_by_asset[asset] = {"enabled": True, "conditions": conditions}

        signal_overrides = {dot: params[toml_key] for toml_key, dot in _SIGNAL_TOML_KEYS.items() if toml_key in params}
        if signal_overrides:
            indicator_by_asset[asset] = {"signal": signal_overrides}

    return {
        "Strategy_by_asset": strategy_by_asset,
        "Indicator_by_asset": indicator_by_asset,
    }


@contextmanager
def _original_strategy_bridge() -> object:
    """Expose the original Strategy package only while its frame pipeline runs."""
    original = str(_ORIGINAL_REPO)
    rebuild = str(_ROOT)
    if not (_ORIGINAL_REPO / "Strategy" / "getData.py").is_file():
        raise RuntimeError(f"Original Strategy source is unavailable: {_ORIGINAL_REPO}")

    with _IMPORT_LOCK:
        saved_modules = {
            name: module
            for name, module in sys.modules.items()
            if name == "Strategy" or name.startswith("Strategy.")
        }
        for name in list(saved_modules):
            del sys.modules[name]

        saved_path = list(sys.path)
        sys.path[:] = [path for path in sys.path if path not in (original, rebuild)]
        sys.path.insert(0, original)
        try:
            from Strategy.getData import build_final_strategy_dataframe  # type: ignore[import]

            yield build_final_strategy_dataframe
        finally:
            for name in list(sys.modules):
                if name == "Strategy" or name.startswith("Strategy."):
                    del sys.modules[name]
            sys.modules.update(saved_modules)
            sys.path[:] = saved_path


def _validate(frame: pl.DataFrame) -> None:
    missing = set(FRAME_COLUMNS) - set(frame.columns)
    if missing:
        raise RuntimeError(f"Frame pipeline missing columns: {sorted(missing)}")


def build(
    ohlcv: pl.DataFrame,
    progress: Callable[[str], None] | None = None,
    *,
    n_workers: int | None = None,
) -> pl.DataFrame:
    """Run the full Hercules strategy pipeline and return Hercules Frame.

    Multi-asset input processed in parallel (one thread per asset).
    Each asset sees only its own data — no cross-asset leakage.

    Columns produced: timestamp, open, high, low, close, volume, asset,
    direction, short_trend_similarity, final_signal (Int8), slope.
    """
    with _original_strategy_bridge() as build_final_strategy_dataframe:
        config = _build_config()
        assets = ohlcv["asset"].unique().to_list()

        if len(assets) <= 1:
            frame = build_final_strategy_dataframe(ohlcv, config=config, progress=progress)
            _validate(frame)
            return frame.select(*FRAME_COLUMNS)

        # Multi-asset: each asset slice is independent — split, compute in parallel, concat.
        n = min(len(assets), n_workers or os.cpu_count() or 4)
        lock = threading.Lock()

        def _build_one(asset: str) -> pl.DataFrame:
            result = build_final_strategy_dataframe(
                ohlcv.filter(pl.col("asset") == asset),
                config=config,
            )
            if progress is not None:
                with lock:
                    progress(asset)
            return result

        with ThreadPoolExecutor(max_workers=n, thread_name_prefix="frame") as pool:
            parts = list(pool.map(_build_one, assets))

        frame = pl.concat(parts).sort("timestamp", "asset")
        _validate(frame)
        return frame.select(*FRAME_COLUMNS)
