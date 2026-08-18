"""Hercules Frame pipeline — delegates to Strategy.getData via original repo bridge."""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

import polars as pl

_ORIGINAL_REPO = Path("/home/void/Documents/Hercules 3.0")
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
    """Build config dict matching the original backtester's Strategy_by_asset format."""
    with _STRATEGY_TOML.open("rb") as f:
        cfg = tomllib.load(f)

    global_conditions = cfg.get("conditions", {})
    asset_params = cfg.get("assets", {})

    # base global conditions — same defaults as strategy.py disk config
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
        # merge per-asset condition overrides onto base (mirrors resolve_strategy_params)
        conditions = dict(base)
        for field in _ALL_CONDITION_FIELDS:
            if field in params:
                conditions[field] = params[field]
        strategy_by_asset[asset] = {"enabled": True, "conditions": conditions}

        # signal threshold overrides (dot-notation for _apply_overrides)
        signal_overrides = {dot: params[toml_key] for toml_key, dot in _SIGNAL_TOML_KEYS.items() if toml_key in params}
        if signal_overrides:
            indicator_by_asset[asset] = {"signal": signal_overrides}

    return {
        "Strategy_by_asset": strategy_by_asset,
        "Indicator_by_asset": indicator_by_asset,
    }


def _ensure_original_on_path() -> None:
    rebuild = str(_ORIGINAL_REPO.parent / "hercules 3.0 rebuilt")
    original = str(_ORIGINAL_REPO)
    # original appended so rebuild modules resolve first (avoids package name collisions)
    if original not in sys.path:
        sys.path.append(original)
    if rebuild not in sys.path:
        sys.path.insert(0, rebuild)
    elif sys.path[0] != rebuild:
        sys.path.remove(rebuild)
        sys.path.insert(0, rebuild)


def build(
    ohlcv: pl.DataFrame,
    progress: Callable[[str], None] | None = None,
) -> pl.DataFrame:
    """Run the full Hercules strategy pipeline and return Hercules Frame.

    Columns produced: timestamp, open, high, low, close, volume, asset,
    direction, short_trend_similarity, final_signal (Int8), slope.
    """
    _ensure_original_on_path()
    from Strategy.getData import build_final_strategy_dataframe  # type: ignore[import]

    config = _build_config()
    frame = build_final_strategy_dataframe(ohlcv, config=config, progress=progress)

    missing = set(FRAME_COLUMNS) - set(frame.columns)
    if missing:
        raise RuntimeError(f"Frame pipeline missing columns: {sorted(missing)}")

    return frame.select(*FRAME_COLUMNS)
