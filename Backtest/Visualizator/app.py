"""Optimized localhost Dash visualizer matching Hercules 3.0."""

from __future__ import annotations

import socket
import threading
import webbrowser
from datetime import datetime, timezone
from itertools import groupby
from math import ceil
from typing import cast

import plotly.graph_objects as go
import polars as pl

from .equity import build_equity_figure

_TRADE_COLORS = {("long", "win"): "#2ecc71", ("long", "lose"): "#e74c3c", ("short", "win"): "#f39c12", ("short", "lose"): "#9b59b6"}
_TREND_COLORS = {"BULLISH": "#2ecc71", "BEARISH": "#e74c3c"}
_MAX_CANDLES = 300


def resample_candles(frame: pl.DataFrame) -> pl.DataFrame:
    """Preserve OHLC extremes while capping chart candles at 300."""
    if frame.height <= _MAX_CANDLES:
        return frame
    step = max(2, ceil(frame.height / _MAX_CANDLES))
    return (
        frame.with_row_index("_index").with_columns((pl.col("_index") // step).alias("_group"))
        .group_by("_group").agg(
            pl.col("timestamp").first(), pl.col("open").first(), pl.col("high").max(),
            pl.col("low").min(), pl.col("close").last(), pl.col("direction").last(),
        ).sort("timestamp").drop("_group")
    )


def _parse_timestamp(value: str) -> datetime:
    clean = value.split(".")[0].split("+")[0].replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            continue
    raise ValueError(f"unknown Plotly timestamp: {value!r}")


def _literal(value: datetime, frame: pl.DataFrame) -> pl.Expr:
    if getattr(frame.schema["timestamp"], "time_zone", None) and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return pl.lit(value).cast(frame.schema["timestamp"])


def _asset_traces(rows: list[dict[str, object]], trades: list[dict[str, object]]) -> list[dict[str, object]]:
    timestamps, closes = [row["timestamp"] for row in rows], [row["close"] for row in rows]
    traces: list[dict[str, object]] = [{
        "type": "candlestick", "x": timestamps, "open": [row["open"] for row in rows],
        "high": [row["high"] for row in rows], "low": [row["low"] for row in rows], "close": closes,
        "increasing": {"line": {"color": "#fff"}, "fillcolor": "#fff"},
        "decreasing": {"line": {"color": "#888"}, "fillcolor": "#000"}, "name": "Candles",
    }]
    start = 0
    for direction, group in groupby(str(row["direction"]) for row in rows):
        end = start + sum(1 for _ in group) - 1
        traces.append({"type": "scattergl", "x": timestamps[max(0, start - 1): end + 1], "y": closes[max(0, start - 1): end + 1], "mode": "lines", "line": {"color": _TREND_COLORS.get(direction, "#95a5a6"), "width": 2}, "hoverinfo": "skip", "showlegend": False})
        start = end + 1
    for kind, color in _TRADE_COLORS.items():
        selected = [trade for trade in trades if (str(trade["type"]), str(trade["outcome"])) == kind]
        if not selected:
            continue
        is_long = kind[0] == "long"
        entries = [trade["timestamp"] for trade in selected]
        opens = [float(cast(float | int | str, trade["open"])) for trade in selected]
        exits = [trade["exit_timestamp"] for trade in selected]
        exit_prices = [float(cast(float | int | str, trade["exit_price"])) for trade in selected]
        lines_x = [point for trade in selected for point in (trade["timestamp"], trade["exit_timestamp"], None)]
        lines_y = [point for trade in selected for point in (float(cast(float | int | str, trade["open"])), float(cast(float | int | str, trade["exit_price"])), None)]
        traces.extend([
            {"type": "scattergl", "x": lines_x, "y": lines_y, "mode": "lines", "line": {"color": color, "width": 1, "dash": "dot"}, "hoverinfo": "skip", "showlegend": False},
            {"type": "scattergl", "x": entries, "y": opens, "mode": "markers", "marker": {"color": color, "size": 14, "symbol": "triangle-up" if is_long else "triangle-down"}, "name": f"{kind[0]} {kind[1]} entry"},
            {"type": "scattergl", "x": exits, "y": exit_prices, "mode": "markers", "marker": {"color": color, "size": 12, "symbol": "triangle-down" if is_long else "triangle-up"}, "name": f"{kind[0]} {kind[1]} exit"},
        ])
    return traces


def _asset_figure(frame: pl.DataFrame, trades: pl.DataFrame, asset: str, start: datetime | None = None, end: datetime | None = None) -> go.Figure:
    candles = frame.filter(pl.col("asset") == asset).sort("timestamp")
    asset_trades = trades.filter(pl.col("asset") == asset).sort("timestamp")
    if start is not None and end is not None:
        span = max((end - start).total_seconds(), 1.0)
        buffer = pl.duration(milliseconds=int(span * 200))
        left, right = _literal(start, candles), _literal(end, candles)
        candles = candles.filter((pl.col("timestamp") >= left - buffer) & (pl.col("timestamp") <= right + buffer))
        asset_trades = asset_trades.filter((pl.col("timestamp") <= right + buffer) & (pl.col("exit_timestamp") >= left - buffer))
    elif not asset_trades.is_empty():
        candles = candles.filter((pl.col("timestamp") >= asset_trades["timestamp"].min()) & (pl.col("timestamp") <= asset_trades["exit_timestamp"].max()))
    rows = resample_candles(candles).to_dicts()
    if not rows:
        return go.Figure(layout={"template": "plotly_dark", "uirevision": asset})
    lows, highs = [float(row["low"]) for row in rows], [float(row["high"]) for row in rows]
    padding = max((max(highs) - min(lows)) * 0.05, max(highs) * 0.001)
    figure = go.Figure(data=_asset_traces(rows, asset_trades.to_dicts()))
    figure.update_layout(
        template="plotly_dark", uirevision=asset, title=f"{asset} — candles, trend, trades",
        xaxis_title="Date", yaxis_title="Price", xaxis_rangeslider_visible=False,
        xaxis_range=[rows[0]["timestamp"], rows[-1]["timestamp"]],
        yaxis_range=[min(lows) - padding, max(highs) + padding], hovermode="closest",
        showlegend=False, margin={"l": 60, "r": 40, "t": 60, "b": 60},
    )
    return figure


def launch_visualizer(strategy: pl.DataFrame, trades: pl.DataFrame, equity: pl.DataFrame, *, results: pl.DataFrame | None = None, open_browser: bool = True) -> None:
    """Start a local interactive chart server; imports Dash only when requested."""
    from dash import Dash, Input, Output, callback_context, dcc, html

    if strategy.is_empty() or equity.is_empty():
        raise ValueError("visualizer requires non-empty Strategy and Equity dataframes")
    assets = strategy["asset"].unique().sort().to_list()
    equity_assets = equity["asset"].unique().sort().to_list()
    equity_assets = [asset for asset in equity_assets if asset != "TOTAL"] + (["TOTAL"] if "TOTAL" in equity_assets else [])
    total_pnl = float(cast(float | int | str, trades["pnl"].sum() or 0.0)) if not trades.is_empty() else 0.0
    win_rate = float(cast(float | int | str, (trades["outcome"] == "win").mean() or 0.0)) if not trades.is_empty() else 0.0
    stats = f"TOTAL  Trades {trades.height}  PnL ${total_pnl:,.2f}  Win rate {win_rate:.1%}"
    tab = {"backgroundColor": "#111", "color": "#888", "border": "none", "padding": "6px 14px"}
    selected = {**tab, "backgroundColor": "#222", "color": "#fff", "borderBottom": "2px solid #4fc3f7"}
    app = Dash(__name__, suppress_callback_exceptions=True)
    app.layout = html.Div([
        html.Div(stats, style={"padding": "8px 12px", "backgroundColor": "#111", "color": "#ccc"}),
        dcc.Tabs(id="view", value="price", children=[dcc.Tab(label="Price", value="price", style=tab, selected_style=selected), dcc.Tab(label="Equity", value="equity", style=tab, selected_style=selected)]),
        html.Div([
            dcc.Tabs(id="asset", value=assets[0], children=[dcc.Tab(label=asset, value=asset, style=tab, selected_style=selected) for asset in assets]),
            dcc.Graph(id="price", figure=_asset_figure(strategy, trades, assets[0]), config={"scrollZoom": True, "displaylogo": False}, style={"height": "calc(100vh - 100px)"}),
        ], id="price-panel"),
        html.Div([
            dcc.Tabs(id="equity-asset", value=equity_assets[0], children=[dcc.Tab(label=asset, value=asset, style=tab, selected_style=selected) for asset in equity_assets]),
            dcc.Graph(id="equity", figure=build_equity_figure(equity.filter(pl.col("asset") == equity_assets[0])), config={"scrollZoom": True, "displaylogo": False}, style={"height": "calc(100vh - 100px)"}),
        ], id="equity-panel", style={"display": "none"}),
    ], style={"backgroundColor": "#111", "margin": "0"})

    @app.callback(Output("price", "figure"), Input("asset", "value"), Input("price", "relayoutData"))
    def update_price(asset: str, relayout: dict[str, object] | None) -> go.Figure:
        start = end = None
        if callback_context.triggered and relayout:
            left, right = relayout.get("xaxis.range[0]"), relayout.get("xaxis.range[1]")
            if isinstance(left, str) and isinstance(right, str):
                try:
                    start, end = _parse_timestamp(left), _parse_timestamp(right)
                except ValueError:
                    pass
        return _asset_figure(strategy, trades, asset, start, end)

    @app.callback(Output("price-panel", "style"), Output("equity-panel", "style"), Input("view", "value"))
    def choose_view(view: str) -> tuple[dict[str, str], dict[str, str]]:
        return ({}, {"display": "none"}) if view == "price" else ({"display": "none"}, {})

    @app.callback(Output("equity", "figure"), Input("equity-asset", "value"))
    def update_equity(asset: str) -> go.Figure:
        return build_equity_figure(equity.filter(pl.col("asset") == asset))

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=app.run, kwargs={"port": port, "debug": False, "use_reloader": False}, daemon=True, name="backtest-dash").start()
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open_new_tab(url)).start()
    print(f"Visualizator listening on {url}", flush=True)
