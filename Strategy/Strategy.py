"""Apply Rust strategy core to Hercules Frame — stateful per-asset position tracking."""

from __future__ import annotations

import math
import tomllib
from pathlib import Path

import polars as pl

_SHARED_DATA = Path(__file__).parent.parent / "SharedData"
_STRATEGY_TOML = _SHARED_DATA / "Strategy.toml"

_RISK_KEYS = (
    "leverage",
    "trade_size_pct",
    "take_profit_pct",
    "checkpoint_trail_pct",
    "short_trailing_stop_pct",
    "stop_loss_pct",
)

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


def asset_risk_params(asset: str, portfolio_toml: Path | None = None) -> dict:
    """Merged risk params for asset: Strategy.toml per-asset overrides Portfolio.toml base."""
    _pf = portfolio_toml or (_SHARED_DATA / "Portfolio.toml")
    with _STRATEGY_TOML.open("rb") as f:
        strategy = tomllib.load(f)
    with _pf.open("rb") as f:
        portfolio = tomllib.load(f)
    result: dict = {k: portfolio.get(k) for k in _RISK_KEYS}
    for k, v in result.items():
        if v is not None:
            result[k] = float(v)
    for k in _RISK_KEYS:
        if k in strategy.get("assets", {}).get(asset, {}):
            result[k] = float(strategy["assets"][asset][k])
    return result


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

        # LONGs have no exit — suppress reversal_to_short, preserve exposure
        long_suppressed = result.reason == "reversal_to_short" and current_exposure > 1e-9
        if long_suppressed:
            action_out = "Hold"
            side_out = "Long"
            target_out = current_exposure
            delta_out = 0.0
            entry_allowed_out = False
            exit_required_out = False
            reason_out = "long_hold_no_exit"
        else:
            action_out = result.action
            side_out = result.side
            target_out = result.target_exposure
            delta_out = result.exposure_delta
            entry_allowed_out = result.entry_allowed
            exit_required_out = result.exit_required
            reason_out = result.reason

        if entry_allowed_out:
            exposure[asset] = target_out

        results.append(
            {
                "timestamp": row["timestamp"],
                "asset": asset,
                "action": action_out,
                "side": side_out,
                "target_exposure": target_out,
                "exposure_delta": delta_out,
                "entry_allowed": entry_allowed_out,
                "exit_required": exit_required_out,
                "reason": reason_out,
            }
        )

    decisions = pl.DataFrame(results)
    return frame.join(decisions, on=["timestamp", "asset"], how="left")
