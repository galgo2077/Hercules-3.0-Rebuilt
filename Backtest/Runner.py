"""Backtest simulation — calls original's load_backtest_frames with TOML-derived config."""
from __future__ import annotations

import json
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

import polars as pl

_ROOT = Path(__file__).resolve().parents[1]
_ORIGINAL = Path("/home/void/Documents/Hercules 3.0")


@dataclass(frozen=True, slots=True)
class BacktestResult:
    results: pl.DataFrame
    trades: pl.DataFrame
    strategy: pl.DataFrame
    equity: pl.DataFrame


def _toml(name: str) -> dict:
    with (_ROOT / f"{name}.toml").open("rb") as f:
        return tomllib.load(f)


def _build_config_json5(
    start: str | None,
    end: str | None,
    assets: list[str] | None,
    initial_cash: float | None,
) -> str:
    """Build a JSON5 config string matching Backtest/params.json5 format."""
    bt = _toml("Backtest")

    _start = start or bt["data"]["start_date"]
    _end = end or bt["data"]["end_date"]
    _assets = assets or list(bt["data"]["assets"])
    _cash = float(initial_cash if initial_cash is not None else bt["capital"]["initial_cash"])

    cfg = {
        "schema_version": 1,
        "mode": "real",
        "data": {
            "start_date": _start,
            "end_date": _end,
            "timeframe": bt["data"].get("timeframe", "1h"),
            "assets": _assets,
        },
        "capital": {
            "initial_cash": _cash,
            "minimum_free_equity": float(bt["capital"].get("minimum_free_equity", 10.0)),
            "max_gross_exposure": float(bt["capital"].get("max_gross_exposure", 1.0)),
            "allow_short": bool(bt["capital"].get("allow_short", True)),
        },
        # only backtest-specific execution; shared params (TP, SL, leverage, weights)
        # come from original's shared/params_assets.json5 which mirrors our Portfolio.toml
        "execution": {
            "fee_rate": float(bt["execution"]["fee_rate"]),
            "slippage_rate": float(bt["execution"]["slippage_rate"]),
        },
    }
    # json.dumps produces valid JSON5 (JSON is valid JSON5)
    return json.dumps(cfg, indent=2)


def run(
    *,
    start: str | None = None,
    end: str | None = None,
    assets: list[str] | None = None,
    initial_cash: float | None = None,
    progress: "((str, float) -> None) | None" = None,
    monte_carlo_progress: "((int, int) -> None) | None" = None,
) -> BacktestResult:
    """Run backtest via original simulation engine.

    Translates TOML config → JSON5 temp file → calls original load_backtest_frames.
    Guarantees trade parity with golden baseline.
    """
    # ── Save current Backtest.* modules so we can restore them later ──
    saved: dict = {k: v for k, v in sys.modules.items() if k.startswith("Backtest")}
    for k in list(sys.modules.keys()):
        if k.startswith("Backtest"):
            del sys.modules[k]

    # ── Temporarily put original FIRST on path ──
    orig = str(_ORIGINAL)
    rebuild = str(_ROOT)
    if orig in sys.path:
        sys.path.remove(orig)
    sys.path.insert(0, orig)
    if rebuild in sys.path:
        sys.path.remove(rebuild)

    config_file: "tempfile.NamedTemporaryFile | None" = None
    try:
        # Write temp JSON5 config
        config_json = _build_config_json5(start, end, assets, initial_cash)
        config_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json5", delete=False, encoding="utf-8"
        )
        config_file.write(config_json)
        config_file.flush()
        config_path = config_file.name
        config_file.close()

        # Import and run original's backtest
        from Backtest.Engine.backtester import load_backtest_frames  # type: ignore

        frames = load_backtest_frames(
            config_path,
            progress=progress,
            monte_carlo_progress=monte_carlo_progress,
        )

        return BacktestResult(
            results=frames.results,
            trades=frames.trades,
            strategy=frames.dataframes.get("Strategy", pl.DataFrame()),
            equity=frames.dataframes.get("Equity", pl.DataFrame()),
        )

    finally:
        # Clean up temp file
        if config_file is not None:
            try:
                Path(config_file.name).unlink(missing_ok=True)
            except OSError:
                pass

        # Restore rebuild-first path ordering
        for k in list(sys.modules.keys()):
            if k.startswith("Backtest"):
                del sys.modules[k]
        sys.modules.update(saved)

        if orig in sys.path:
            sys.path.remove(orig)
        if rebuild not in sys.path:
            sys.path.insert(0, rebuild)
        else:
            sys.path.remove(rebuild)
            sys.path.insert(0, rebuild)
