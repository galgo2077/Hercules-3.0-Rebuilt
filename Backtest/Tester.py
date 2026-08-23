"""Backtest module tester — pre-integration check. Run: python Backtest/Tester.py [--full]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

passed = 0
total = 0


def check(label: str, fn):
    global passed, total
    total += 1
    try:
        fn()
        print(f"[PASS] {label}")
        passed += 1
    except Exception as e:
        print(f"[FAIL] {label}: {e}")


# 1. Runner imports
def _runner_import():
    from Backtest.Runner import BacktestResult, run  # noqa: F401


check("Runner imports", _runner_import)


# 2. BacktestResult fields
def _result_fields():
    import dataclasses

    from Backtest.Runner import BacktestResult

    fields = {f.name for f in dataclasses.fields(BacktestResult)}
    missing = {"results", "trades", "strategy", "equity"} - fields
    if missing:
        raise AssertionError(f"missing fields: {missing}")


check("BacktestResult fields", _result_fields)


# 3. Tui imports
def _tui_import():
    from Backtest.Tui import BacktestProgress, print_results  # noqa: F401


check("Tui imports", _tui_import)


# 4. BacktestProgress context
def _progress_ctx():
    from Backtest.Tui import BacktestProgress

    with BacktestProgress(["BTCUSDT"]):
        pass


check("BacktestProgress context", _progress_ctx)


# 5. Auto tuner only samples contiguous 50% real-candle windows
def _tuner_paths():
    from datetime import timedelta

    from Backtest.Tuner import _paths

    paths = _paths(
        {"start_date": "2020-01-01T00:00:00Z", "end_date": "2022-01-01T00:00:00Z"},
        {"training_fraction": 0.5, "paths": 3, "seed": 42},
    )
    if len(paths) != 3:
        raise AssertionError(f"expected 3 paths, got {len(paths)}")
    for start, end in paths:
        if _date(end) - _date(start) != timedelta(days=365, hours=12):
            raise AssertionError(f"path is not 50% of source range: {start} to {end}")


def _date(value):
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


check("Auto tuner uses 50% candle windows", _tuner_paths)

# 5. Full backtest (slow)
if "--full" in sys.argv:
    total += 1
    try:
        from Backtest.Runner import run

        result = run()
        if result.trades.height != 7:
            raise AssertionError(f"expected 7 trades, got {result.trades.height}")
        print(f"[PASS] full backtest: {result.trades.height} trades")
        print(f"       first trade: {result.trades.row(0, named=True)}")
        passed += 1
    except Exception as e:
        print(f"[FAIL] full backtest: {e}")
else:
    print("[SKIP] full backtest (pass --full to run)")

print(f"\n{passed}/{total} passed")
