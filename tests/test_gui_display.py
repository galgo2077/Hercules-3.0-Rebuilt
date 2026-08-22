"""GUI display verification tests for Backtest/Visualizator."""

from __future__ import annotations

import datetime

import plotly.graph_objects as go
import polars as pl
import pytest

from Backtest.Visualizator.app import (
    _TRADE_COLORS,
    _TREND_COLORS,
    _asset_figure,
    _asset_traces,
    resample_candles,
)
from Backtest.Visualizator.equity import build_equity_figure

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)


def _make_candles(n: int = 10, asset: str = "BTCUSDT") -> pl.DataFrame:
    directions = (["BULLISH", "BEARISH"] * (n // 2 + 1))[:n]
    return pl.DataFrame(
        {
            "timestamp": [_BASE + datetime.timedelta(hours=i) for i in range(n)],
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i for i in range(n)],
            "volume": [1000.0] * n,
            "asset": [asset] * n,
            "direction": directions,
            "short_trend_similarity": [0.5] * n,
            "final_signal": ([1, -1] * (n // 2 + 1))[:n],
            "slope": ([0.01, -0.01] * (n // 2 + 1))[:n],
        }
    )


def _make_resample_frame(
    n: int,
    *,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    opens: list[float] | None = None,
    closes: list[float] | None = None,
    directions: list[str] | None = None,
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "timestamp": [_BASE + datetime.timedelta(hours=i) for i in range(n)],
            "open": opens if opens is not None else [100.0 + i for i in range(n)],
            "high": highs if highs is not None else [101.0 + i for i in range(n)],
            "low": lows if lows is not None else [99.0 + i for i in range(n)],
            "close": closes if closes is not None else [100.5 + i for i in range(n)],
            "direction": directions if directions is not None else ["BULLISH"] * n,
        }
    )


def _make_trade(
    asset: str = "BTCUSDT",
    type_: str = "long",
    outcome: str = "win",
    open_price: float = 100.0,
    exit_price: float = 103.0,
) -> dict:
    return {
        "timestamp": _BASE + datetime.timedelta(hours=1),
        "exit_timestamp": _BASE + datetime.timedelta(hours=5),
        "asset": asset,
        "type": type_,
        "outcome": outcome,
        "open": open_price,
        "exit_price": exit_price,
    }


def _trades_df(*trades: dict) -> pl.DataFrame:
    if not trades:
        return pl.DataFrame(
            {
                "timestamp": pl.Series([], dtype=pl.Datetime("us", "UTC")),
                "exit_timestamp": pl.Series([], dtype=pl.Datetime("us", "UTC")),
                "asset": pl.Series([], dtype=pl.Utf8),
                "type": pl.Series([], dtype=pl.Utf8),
                "outcome": pl.Series([], dtype=pl.Utf8),
                "open": pl.Series([], dtype=pl.Float64),
                "exit_price": pl.Series([], dtype=pl.Float64),
            }
        )
    return pl.DataFrame(list(trades))


def _equity_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "asset": ["TOTAL"],
            "timestamp": [_BASE],
            "equity": [10000.0],
        }
    )


# ---------------------------------------------------------------------------
# A. resample_candles
# ---------------------------------------------------------------------------


def test_resample_no_reduction_under_300() -> None:
    frame = _make_resample_frame(100)
    assert resample_candles(frame).height == 100


def test_resample_exactly_300() -> None:
    frame = _make_resample_frame(300)
    assert resample_candles(frame).height == 300


def test_resample_reduces_over_300() -> None:
    frame = _make_resample_frame(600)
    assert resample_candles(frame).height <= 300


def test_resample_high_is_max() -> None:
    n = 302
    highs = [110.0, 120.0] + [105.0] * (n - 2)
    frame = _make_resample_frame(n, highs=highs)
    resampled = resample_candles(frame)
    assert resampled["high"][0] == 120.0


def test_resample_low_is_min() -> None:
    n = 302
    lows = [90.0, 80.0] + [95.0] * (n - 2)
    frame = _make_resample_frame(n, lows=lows)
    resampled = resample_candles(frame)
    assert resampled["low"][0] == 80.0


def test_resample_open_is_first() -> None:
    n = 302
    opens = [42.0] + [100.0] * (n - 1)
    frame = _make_resample_frame(n, opens=opens)
    resampled = resample_candles(frame)
    assert resampled["open"][0] == 42.0


def test_resample_close_is_last() -> None:
    n = 302
    closes = [100.0] * (n - 1) + [99.9]
    frame = _make_resample_frame(n, closes=closes)
    resampled = resample_candles(frame)
    assert resampled["close"][-1] == 99.9


# ---------------------------------------------------------------------------
# B. _asset_traces — candlestick trace
# ---------------------------------------------------------------------------


def test_traces_first_is_candlestick() -> None:
    rows = _make_candles(5).to_dicts()
    traces = _asset_traces(rows, [])
    assert traces[0]["type"] == "candlestick"


def test_traces_candlestick_has_ohlc() -> None:
    rows = _make_candles(5).to_dicts()
    traces = _asset_traces(rows, [])
    cs = traces[0]
    for key in ("open", "high", "low", "close"):
        assert key in cs


def test_traces_candlestick_price_count() -> None:
    rows = _make_candles(5).to_dicts()
    traces = _asset_traces(rows, [])
    cs = traces[0]
    assert len(cs["open"]) == 5


# ---------------------------------------------------------------------------
# C. _asset_traces — trend line traces
# ---------------------------------------------------------------------------


def test_traces_includes_trend_line() -> None:
    rows = _make_candles(5).to_dicts()
    traces = _asset_traces(rows, [])
    line_traces = [t for t in traces if t.get("type") == "scattergl" and t.get("mode") == "lines"]
    assert len(line_traces) >= 1


def test_traces_bullish_trend_color() -> None:
    frame = _make_candles(5)
    rows = frame.with_columns(pl.lit("BULLISH").alias("direction")).to_dicts()
    traces = _asset_traces(rows, [])
    line_traces = [
        t for t in traces
        if t.get("type") == "scattergl" and t.get("mode") == "lines"
    ]
    colors = {t["line"]["color"] for t in line_traces}
    assert _TREND_COLORS["BULLISH"] in colors


def test_traces_bearish_trend_color() -> None:
    frame = _make_candles(5)
    rows = frame.with_columns(pl.lit("BEARISH").alias("direction")).to_dicts()
    traces = _asset_traces(rows, [])
    line_traces = [
        t for t in traces
        if t.get("type") == "scattergl" and t.get("mode") == "lines"
    ]
    colors = {t["line"]["color"] for t in line_traces}
    assert _TREND_COLORS["BEARISH"] in colors


# ---------------------------------------------------------------------------
# D. _asset_traces — trade markers
# ---------------------------------------------------------------------------


def test_traces_long_win_entry_triangle_up() -> None:
    rows = _make_candles(10).to_dicts()
    traces = _asset_traces(rows, [_make_trade(type_="long", outcome="win")])
    entries = [t for t in traces if t.get("mode") == "markers" and "entry" in str(t.get("name", ""))]
    assert entries, "no entry marker trace found"
    assert entries[0]["marker"]["symbol"] == "triangle-up"


def test_traces_long_win_exit_triangle_down() -> None:
    rows = _make_candles(10).to_dicts()
    traces = _asset_traces(rows, [_make_trade(type_="long", outcome="win")])
    exits = [t for t in traces if t.get("mode") == "markers" and "exit" in str(t.get("name", ""))]
    assert exits, "no exit marker trace found"
    assert exits[0]["marker"]["symbol"] == "triangle-down"


def test_traces_short_win_entry_triangle_down() -> None:
    rows = _make_candles(10).to_dicts()
    traces = _asset_traces(rows, [_make_trade(type_="short", outcome="win")])
    entries = [t for t in traces if t.get("mode") == "markers" and "entry" in str(t.get("name", ""))]
    assert entries, "no entry marker trace found"
    assert entries[0]["marker"]["symbol"] == "triangle-down"


def test_traces_short_win_exit_triangle_up() -> None:
    rows = _make_candles(10).to_dicts()
    traces = _asset_traces(rows, [_make_trade(type_="short", outcome="win")])
    exits = [t for t in traces if t.get("mode") == "markers" and "exit" in str(t.get("name", ""))]
    assert exits, "no exit marker trace found"
    assert exits[0]["marker"]["symbol"] == "triangle-up"


def test_traces_long_win_color() -> None:
    rows = _make_candles(10).to_dicts()
    traces = _asset_traces(rows, [_make_trade(type_="long", outcome="win")])
    marker_traces = [t for t in traces if t.get("mode") == "markers"]
    colors = {t["marker"]["color"] for t in marker_traces}
    assert _TRADE_COLORS[("long", "win")] in colors


def test_traces_long_lose_color() -> None:
    rows = _make_candles(10).to_dicts()
    traces = _asset_traces(rows, [_make_trade(type_="long", outcome="lose")])
    marker_traces = [t for t in traces if t.get("mode") == "markers"]
    colors = {t["marker"]["color"] for t in marker_traces}
    assert _TRADE_COLORS[("long", "lose")] in colors


def test_traces_short_win_color() -> None:
    rows = _make_candles(10).to_dicts()
    traces = _asset_traces(rows, [_make_trade(type_="short", outcome="win")])
    marker_traces = [t for t in traces if t.get("mode") == "markers"]
    colors = {t["marker"]["color"] for t in marker_traces}
    assert _TRADE_COLORS[("short", "win")] in colors


def test_traces_short_lose_color() -> None:
    rows = _make_candles(10).to_dicts()
    traces = _asset_traces(rows, [_make_trade(type_="short", outcome="lose")])
    marker_traces = [t for t in traces if t.get("mode") == "markers"]
    colors = {t["marker"]["color"] for t in marker_traces}
    assert _TRADE_COLORS[("short", "lose")] in colors


def test_traces_no_trades_no_marker_traces() -> None:
    rows = _make_candles(5).to_dicts()
    traces = _asset_traces(rows, [])
    marker_traces = [t for t in traces if t.get("mode") == "markers"]
    assert marker_traces == []


def test_traces_one_long_adds_two_marker_traces() -> None:
    rows = _make_candles(10).to_dicts()
    traces = _asset_traces(rows, [_make_trade(type_="long", outcome="win")])
    marker_traces = [t for t in traces if t.get("mode") == "markers"]
    # entry + exit markers
    assert len(marker_traces) == 2


# ---------------------------------------------------------------------------
# E. _asset_figure
# ---------------------------------------------------------------------------


def test_figure_has_data_for_non_empty_candles() -> None:
    frame = _make_candles(5, asset="BTCUSDT")
    trades = _trades_df(_make_trade("BTCUSDT"))
    fig = _asset_figure(frame, trades, "BTCUSDT")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) > 0


def test_figure_title_contains_asset() -> None:
    frame = _make_candles(5, asset="BTCUSDT")
    trades = _trades_df(_make_trade("BTCUSDT"))
    fig = _asset_figure(frame, trades, "BTCUSDT")
    title = fig.layout.title.text if fig.layout.title else str(fig.to_dict().get("layout", {}).get("title", ""))
    assert "BTCUSDT" in str(title)


def test_figure_empty_candles_returns_figure() -> None:
    frame = _make_candles(5, asset="BTCUSDT")
    trades = _trades_df()
    # "DOESNOTEXIST" asset → filters to empty candles
    fig = _asset_figure(frame, trades, "DOESNOTEXIST")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0


def test_figure_filters_to_asset() -> None:
    btc = _make_candles(5, asset="BTCUSDT")
    eth = _make_candles(5, asset="ETHUSDT")
    frame = pl.concat([btc, eth])
    trades = _trades_df(_make_trade("BTCUSDT"))
    fig = _asset_figure(frame, trades, "BTCUSDT")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) > 0


# ---------------------------------------------------------------------------
# F. launch_visualizer — validation
# ---------------------------------------------------------------------------


def test_launch_visualizer_empty_strategy_raises() -> None:
    try:
        from Backtest.Visualizator.app import launch_visualizer
    except ImportError:
        pytest.skip("dash not installed")
    equity = _equity_df()
    trades = _trades_df()
    with pytest.raises(ValueError):
        launch_visualizer(pl.DataFrame(), trades, equity)


def test_launch_visualizer_empty_equity_raises() -> None:
    try:
        from Backtest.Visualizator.app import launch_visualizer
    except ImportError:
        pytest.skip("dash not installed")
    strategy = _make_candles(5, asset="BTCUSDT")
    trades = _trades_df()
    with pytest.raises(ValueError):
        launch_visualizer(strategy, trades, pl.DataFrame())


def test_launch_visualizer_starts_without_browser(monkeypatch) -> None:
    try:
        from dash import Dash  # noqa: F401
        from Backtest.Visualizator.app import launch_visualizer
    except ImportError:
        pytest.skip("dash not installed")

    import threading as _threading

    started: list[str] = []

    class _FakeThread:
        def __init__(self, *, target=None, kwargs=None, daemon=False, name="") -> None:
            self._name = name

        def start(self) -> None:
            started.append(self._name)

    monkeypatch.setattr("Backtest.Visualizator.app.threading.Thread", _FakeThread)

    strategy = _make_candles(5, asset="BTCUSDT")
    trades = _trades_df(_make_trade("BTCUSDT"))
    equity = _equity_df()

    launch_visualizer(strategy, trades, equity, open_browser=False)
    assert any("backtest-dash" in s for s in started)


# ---------------------------------------------------------------------------
# G. equity figure
# ---------------------------------------------------------------------------


def test_build_equity_figure_returns_figure() -> None:
    eq = _equity_df()
    fig = build_equity_figure(eq)
    assert isinstance(fig, go.Figure)


def test_build_equity_figure_has_data() -> None:
    eq = _equity_df()
    fig = build_equity_figure(eq)
    assert len(fig.data) > 0


def test_build_equity_figure_empty() -> None:
    empty = _equity_df().filter(pl.col("asset") == "DOESNOTEXIST")
    fig = build_equity_figure(empty)
    assert isinstance(fig, go.Figure)
