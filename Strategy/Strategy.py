"""Apply Rust strategy core to Hercules Frame — stateful per-asset position tracking."""

from __future__ import annotations

import math
import tomllib
from pathlib import Path

import polars as pl

_SHARED_DATA = Path(__file__).parent.parent / "SharedData"
_STRATEGY_TOML = _SHARED_DATA / "Strategy.toml"

DECISION_COLUMNS = (
    "timestamp",
    "asset",
    "action",
    "side",
    "target_exposure",
    "exposure_delta",
    "entry_allowed",
    "exit_required",
    "reason",
)


def _load_require_slope() -> bool:
    with _STRATEGY_TOML.open("rb") as f:
        cfg = tomllib.load(f)
    return bool(cfg.get("conditions", {}).get("require_slope_confirmation", True))


def _per_asset_trade_size(asset: str, portfolio_toml: Path) -> float:
    """Return trade_size_pct for asset, applying per-asset override from Strategy.toml."""
    with _STRATEGY_TOML.open("rb") as f:
        strategy = tomllib.load(f)
    with portfolio_toml.open("rb") as f:
        portfolio = tomllib.load(f)

    base = float(portfolio.get("trade_size_pct", 0.30))
    override = strategy.get("assets", {}).get(asset, {}).get("trade_size_pct")
    return float(override) if override is not None else base


def evaluate(
    frame: pl.DataFrame,
    *,
    asset_exposures: dict[str, float] | None = None,
    portfolio_toml: Path | None = None,
) -> pl.DataFrame:
    """Apply Rust strategy core row-by-row to the Hercules Frame.

    Returns frame joined with decision columns:
    action, side, target_exposure, exposure_delta, entry_allowed, exit_required, reason.

    asset_exposures: optional current signed exposure per asset (default all flat).
    portfolio_toml: path to Portfolio.toml (default SharedData directory).
    """
    import _strategy  # Rust native module

    _portfolio_toml = portfolio_toml or (_SHARED_DATA / "Portfolio.toml")
    require_slope = _load_require_slope()

    # current signed exposure per asset (positive=long, negative=short)
    exposure: dict[str, float] = dict(asset_exposures or {})

    results: list[dict] = []

    sorted_frame = frame.sort(["asset", "timestamp"])
    for row in sorted_frame.iter_rows(named=True):
        asset = row["asset"]
        current_exposure = exposure.get(asset, 0.0)
        current_side = 1 if current_exposure > 1e-9 else (-1 if current_exposure < -1e-9 else 0)

        slope = row.get("slope")
        slope_f = slope if (slope is not None and not math.isnan(slope)) else float("nan")

        inp = _strategy.StrategyInput(
            timestamp_ms=int(row["timestamp"].timestamp() * 1000),
            asset=asset,
            direction=row.get("direction"),
            final_signal=int(row["final_signal"]),
            short_trend_similarity=float(row.get("short_trend_similarity") or 0.0),
            slope=slope_f,
            warmup_complete=True,
        )

        long_score, short_score = _strategy.evaluate(inp, current_side, require_slope)

        trade_size = _per_asset_trade_size(asset, _portfolio_toml)
        result = _strategy.build_decision(
            inp.timestamp_ms,
            asset,
            long_score,
            short_score,
            current_exposure,
            trade_size,
            trade_size,
        )

        # update exposure tracking
        if result.entry_allowed:
            exposure[asset] = result.target_exposure

        results.append(
            {
                "timestamp": row["timestamp"],
                "asset": asset,
                "action": result.action,
                "side": result.side,
                "target_exposure": result.target_exposure,
                "exposure_delta": result.exposure_delta,
                "entry_allowed": result.entry_allowed,
                "exit_required": result.exit_required,
                "reason": result.reason,
            }
        )

    decisions = pl.DataFrame(results)
    return frame.join(decisions, on=["timestamp", "asset"], how="left")
