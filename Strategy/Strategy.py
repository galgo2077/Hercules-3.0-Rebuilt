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


def asset_risk_params(
    asset: str,
    portfolio_toml: Path | None = None,
    strategy_config: dict | None = None,
    portfolio_config: dict | None = None,
) -> dict:
    """Merged risk params for asset: Strategy.toml per-asset overrides Portfolio.toml base."""
    _pf = portfolio_toml or (_SHARED_DATA / "Portfolio.toml")
    if strategy_config is None:
        with _STRATEGY_TOML.open("rb") as f:
            strategy = tomllib.load(f)
    else:
        strategy = strategy_config
    if portfolio_config is None:
        with _pf.open("rb") as f:
            portfolio_config = tomllib.load(f)
    portfolio = portfolio_config
    result: dict = {k: portfolio.get(k) for k in _RISK_KEYS}
    for k, v in result.items():
        if v is not None:
            result[k] = float(v)
    for k in _RISK_KEYS:
        if k in strategy.get("assets", {}).get(asset, {}):
            result[k] = float(strategy["assets"][asset][k])
    return result


def _load_require_slope(strategy_config: dict | None = None) -> bool:
    if strategy_config is None:
        with _STRATEGY_TOML.open("rb") as f:
            cfg = tomllib.load(f)
    else:
        cfg = strategy_config
    return bool(cfg.get("conditions", {}).get("require_slope_confirmation", True))


def decide(
    row: dict,
    current_exposure: float,
    *,
    portfolio_toml: Path | None = None,
    strategy_config: dict | None = None,
    portfolio_config: dict | None = None,
) -> dict:
    """Return one target-position decision from current authoritative state."""
    import _strategy

    asset = str(row["asset"])
    signal = int(row["final_signal"])
    if signal not in (-1, 0, 1):
        raise ValueError(f"invalid final_signal for {asset}: {signal}")
    slope = row.get("slope")
    slope_value = float(slope) if slope is not None and math.isfinite(float(slope)) else float("nan")
    current_side = 1 if current_exposure > 1e-9 else (-1 if current_exposure < -1e-9 else 0)
    strategy_input = _strategy.StrategyInput(
        timestamp_ms=int(row["timestamp"].timestamp() * 1000),
        asset=asset,
        direction=row.get("direction"),
        final_signal=signal,
        short_trend_similarity=float(row.get("short_trend_similarity") or 0.0),
        slope=slope_value,
        warmup_complete=True,
    )
    long_score, short_score = _strategy.evaluate(strategy_input, current_side, _load_require_slope(strategy_config))
    target = float(
        asset_risk_params(
            asset,
            portfolio_toml=portfolio_toml,
            strategy_config=strategy_config,
            portfolio_config=portfolio_config,
        )["trade_size_pct"]
    )
    result = _strategy.build_decision(strategy_input.timestamp_ms, asset, long_score, short_score, current_exposure, target, target)
    return {
        "action": result.action,
        "side": result.side,
        "target_exposure": result.target_exposure,
        "exposure_delta": result.exposure_delta,
        "entry_allowed": result.entry_allowed,
        "exit_required": result.exit_required,
        "reason": result.reason,
    }


def evaluate(
    frame: pl.DataFrame,
    *,
    asset_exposures: dict[str, float] | None = None,
    portfolio_toml: Path | None = None,
    strategy_config: dict | None = None,
) -> pl.DataFrame:
    """Apply Rust strategy core row-by-row to the Hercules Frame.

    Returns frame joined with decision columns:
    action, side, target_exposure, exposure_delta, entry_allowed, exit_required, reason.

    asset_exposures: optional current signed exposure per asset (default all flat).
    portfolio_toml: path to Portfolio.toml (default SharedData directory).
    """
    _portfolio_toml = portfolio_toml or (_SHARED_DATA / "Portfolio.toml")
    if frame.is_empty():
        return frame.with_columns(
            *(pl.Series(name, [], dtype=pl.String) for name in ("action", "side", "reason")),
            *(pl.Series(name, [], dtype=pl.Float64) for name in ("target_exposure", "exposure_delta")),
            *(pl.Series(name, [], dtype=pl.Boolean) for name in ("entry_allowed", "exit_required")),
        )
    with _portfolio_toml.open("rb") as handle:
        portfolio_config = tomllib.load(handle)

    # current signed exposure per asset (positive=long, negative=short)
    exposure: dict[str, float] = dict(asset_exposures or {})

    results: list[dict] = []

    sorted_frame = frame.sort(["asset", "timestamp"])
    for row in sorted_frame.iter_rows(named=True):
        asset = row["asset"]
        current_exposure = exposure.get(asset, 0.0)
        decision = decide(
            row,
            current_exposure,
            portfolio_toml=_portfolio_toml,
            strategy_config=strategy_config,
            portfolio_config=portfolio_config,
        )

        if decision["entry_allowed"]:
            exposure[asset] = decision["target_exposure"]

        results.append(
            {
                "timestamp": row["timestamp"],
                "asset": asset,
                **decision,
            }
        )

    decisions = pl.DataFrame(results).with_columns(pl.col("timestamp").cast(frame.schema["timestamp"]))
    return frame.join(decisions, on=["timestamp", "asset"], how="left")
