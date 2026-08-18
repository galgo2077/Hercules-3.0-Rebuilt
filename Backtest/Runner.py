"""Backtest simulation — calls original's load_backtest_frames with TOML-derived config."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import tomllib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import polars as pl

_ROOT = Path(__file__).resolve().parents[1]
_ORIGINAL = Path("/home/void/Documents/Hercules 3.0")
ProgressCallback = Callable[[str, float], None]
MonteCarloProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class BacktestResult:
    results: pl.DataFrame
    trades: pl.DataFrame
    strategy: pl.DataFrame
    equity: pl.DataFrame


def _toml(name: str) -> dict:
    with (_ROOT / "SharedData" / f"{name}.toml").open("rb") as f:
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
        "schema_version": int(bt.get("schema_version", 1)),
        "mode": str(bt.get("mode", "real")),
        "data": {
            "start_date": _start,
            "end_date": _end,
            "timeframe": str(bt["data"].get("timeframe", "1h")),
            "assets": _assets,
        },
        "capital": {
            "initial_cash": _cash,
            "minimum_free_equity": float(bt["capital"].get("minimum_free_equity", 10.0)),
            "max_gross_exposure": float(bt["capital"].get("max_gross_exposure", 1.0)),
            "allow_short": bool(bt["capital"].get("allow_short", True)),
        },
        "execution": {
            "diezmar": None,
            "risk_per_trade_pct": None,
            "compound_equity": False,
            "max_trade_size_percentage": None,
            "higher_timeframe_window": None,
            "pyramiding_max": None,
            **dict(bt["execution"]),
        },
        "monte_carlo": dict(bt.get("monte_carlo", {})),
    }
    # json.dumps produces valid JSON5 (JSON is valid JSON5)
    return json.dumps(cfg, indent=2)


def run(
    *,
    start: str | None = None,
    end: str | None = None,
    assets: list[str] | None = None,
    initial_cash: float | None = None,
    progress: ProgressCallback | None = None,
    monte_carlo_progress: MonteCarloProgressCallback | None = None,
) -> BacktestResult:
    """Run backtest via original simulation engine.

    Translates TOML config → JSON5 temp file → calls original load_backtest_frames.
    Guarantees trade parity with golden baseline.
    """
    # ── Save rebuilt packages; original engine imports both Backtest and Dataframe ──
    original_package_prefixes = ("Backtest", "Dataframe")
    saved: dict = {
        key: value
        for key, value in sys.modules.items()
        if key.startswith(original_package_prefixes)
    }
    for k in list(sys.modules.keys()):
        if k.startswith(original_package_prefixes):
            del sys.modules[k]

    # ── Temporarily put original FIRST on path ──
    orig = str(_ORIGINAL)
    rebuild = str(_ROOT)
    if orig in sys.path:
        sys.path.remove(orig)
    sys.path.insert(0, orig)
    if rebuild in sys.path:
        sys.path.remove(rebuild)

    config_path: str | None = None
    try:
        # Write temp JSON5 config
        config_json = _build_config_json5(start, end, assets, initial_cash)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json5", delete=False, encoding="utf-8") as config_file:
            config_file.write(config_json)
            config_path = config_file.name

        # Import original modules
        import Backtest.Engine.backtester as _bt  # type: ignore
        from Backtest.Engine.backtester import load_backtest_frames  # type: ignore
        from Backtest.Engine.ohlcv_cache import CachingMariaAPI  # type: ignore

        # ── Parallel strategy compute ──────────────────────────────────────────
        # Monkeypatch build_final_strategy_dataframe in the backtester module so
        # load_backtest_frames calls the parallel version transparently.
        # Each asset slice is computed independently → no cross-asset leakage,
        # identical results to sequential execution.
        _seq_build = _bt.build_final_strategy_dataframe
        _prog_lock = threading.Lock()

        def _par_build(ohlcv, config=None, progress=None):  # type: ignore[no-untyped-def]
            asset_list = ohlcv["asset"].unique().to_list()
            if len(asset_list) <= 1:
                return _seq_build(ohlcv, config=config, progress=progress)
            n = min(len(asset_list), os.cpu_count() or 4)

            def _one(asset: str) -> pl.DataFrame:
                f = _seq_build(ohlcv.filter(pl.col("asset") == asset), config=config)
                if progress is not None:
                    with _prog_lock:
                        progress(asset)
                return f

            with ThreadPoolExecutor(max_workers=n, thread_name_prefix="bt_strat") as pool:
                parts = list(pool.map(_one, asset_list))
            return pl.concat(parts).sort("timestamp", "asset")

        _bt.build_final_strategy_dataframe = _par_build
        try:
            cache_dir = _ROOT / ".cache" / "ohlcv"
            frames = load_backtest_frames(
                config_path,
                progress=progress,
                monte_carlo_progress=monte_carlo_progress,
                maria_api=CachingMariaAPI(cache_dir=cache_dir),
            )
        finally:
            _bt.build_final_strategy_dataframe = _seq_build

        trades = frames.trades
        if "side" not in trades.columns and "type" in trades.columns:
            trades = trades.with_columns(pl.col("type").alias("side"))

        return BacktestResult(
            results=frames.results,
            trades=trades,
            strategy=frames.dataframes.get("Strategy", pl.DataFrame()),
            equity=frames.dataframes.get("Equity", pl.DataFrame()),
        )

    finally:
        # Clean up temp file
        if config_path is not None:
            try:
                Path(config_path).unlink(missing_ok=True)
            except OSError:
                pass

        # Restore rebuild-first path ordering
        for k in list(sys.modules.keys()):
            if k.startswith(original_package_prefixes):
                del sys.modules[k]
        sys.modules.update(saved)

        if orig in sys.path:
            sys.path.remove(orig)
        if rebuild not in sys.path:
            sys.path.insert(0, rebuild)
        else:
            sys.path.remove(rebuild)
            sys.path.insert(0, rebuild)
