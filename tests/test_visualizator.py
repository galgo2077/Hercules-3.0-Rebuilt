"""Focused checks for the on-demand backtest visualizer."""

import curses
from typing import cast

import polars as pl

from Backtest.Tui import BacktestDashboard, DashboardView
from Backtest.Visualizator.app import resample_candles


def test_resample_candles_preserves_ohlc_extremes() -> None:
    frame = pl.DataFrame(
        {
            "timestamp": list(range(601)), "open": [float(i) for i in range(601)],
            "high": [float(i + 10) for i in range(601)], "low": [float(i - 10) for i in range(601)],
            "close": [float(i + 1) for i in range(601)], "direction": ["BULLISH"] * 601,
        }
    )
    reduced = resample_candles(frame)
    assert reduced.height <= 300
    assert reduced["open"][0] == 0.0
    assert reduced["high"].max() == 610.0
    assert reduced["low"].min() == -10.0
    assert reduced["close"][-1] == 601.0


def test_o_binding_opens_visualizer_without_blocking_tui(monkeypatch) -> None:
    class Screen:
        def getmaxyx(self) -> tuple[int, int]:
            return (30, 120)

    class InlineThread:
        def __init__(self, *, target, daemon: bool, name: str) -> None:
            self.target = target

        def start(self) -> None:
            self.target()

    opened: list[bool] = []
    monkeypatch.setattr("Backtest.Tui.threading.Thread", InlineThread)
    view = DashboardView("Results", pl.DataFrame({"asset": ["ALL"]}), ("asset",), filter_assets=False)
    dashboard = BacktestDashboard(cast(curses.window, Screen()), "BACKTEST EXPLORER", [view], lambda: opened.append(True))
    dashboard.handle(ord("o"))
    assert opened == [True]
    assert dashboard._chart_message == "Chart visualizer opened."
