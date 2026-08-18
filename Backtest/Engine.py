"""Re-export from Runner to preserve the Engine name for external callers."""

from Backtest.Runner import BacktestResult, run  # noqa: F401

__all__ = ["BacktestResult", "run"]
