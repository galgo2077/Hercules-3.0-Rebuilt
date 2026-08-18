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
    from Backtest.Runner import BacktestResult
    import dataclasses
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

# 5. Visualizer imports
def _viz_import():
    from Backtest.Visualizer import show  # noqa: F401

check("Visualizer imports", _viz_import)

# 6. Full backtest (slow)
if "--full" in sys.argv:
    total += 1
    try:
        from Backtest.Runner import run
        result = run()
        assert result.trades.height == 7, f"expected 7 trades, got {result.trades.height}"
        print(f"[PASS] full backtest: {result.trades.height} trades")
        print(f"       first trade: {result.trades.row(0, named=True)}")
        passed += 1
    except Exception as e:
        print(f"[FAIL] full backtest: {e}")
else:
    print("[SKIP] full backtest (pass --full to run)")

print(f"\n{passed}/{total} passed")
