"""Plotly Dash — equity curves and trade list after backtest."""
from __future__ import annotations

import dash
import plotly.graph_objects as go
from dash import Input, Output, dcc, html

from Backtest.Runner import BacktestResult

_PORT = 8766


def _equity_figure(result: BacktestResult) -> go.Figure:
    fig = go.Figure()
    if result.equity.is_empty():
        return fig
    df = result.equity
    ts_col = next((c for c in df.columns if "time" in c.lower() or c == "ts"), None)
    for col in df.columns:
        if col == ts_col or "time" in col.lower():
            continue
        fig.add_trace(go.Scatter(x=df[ts_col].to_list() if ts_col else list(range(df.height)),
                                 y=df[col].to_list(), name=col, mode="lines"))
    fig.update_layout(title="Equity Curves", xaxis_title="Time", yaxis_title="USDT",
                      template="plotly_dark")
    return fig


def _trades_table(result: BacktestResult) -> list:
    if result.trades.is_empty():
        return [html.P("No trades.")]
    show = ["asset", "side", "outcome", "pnl"]
    cols = [c for c in show if c in result.trades.columns]
    header = html.Tr([html.Th(c) for c in cols])
    rows = [
        html.Tr([html.Td(str(row.get(c, ""))) for c in cols])
        for row in result.trades.iter_rows(named=True)
    ]
    return [html.Table([html.Thead(header), html.Tbody(rows)],
                       style={"width": "100%", "borderCollapse": "collapse"})]


def show(result: BacktestResult, port: int = _PORT, open_browser: bool = True) -> None:
    """Launch Dash app with equity curves and trade table."""
    app = dash.Dash(__name__)
    fig = _equity_figure(result)

    app.layout = html.Div([
        html.H1("Hercules Backtest", style={"fontFamily": "monospace"}),
        dcc.Graph(figure=fig, style={"height": "500px"}),
        html.H2("Trades"),
        html.Div(_trades_table(result), id="trades-table"),
    ], style={"background": "#1a1a1a", "color": "#eee", "padding": "20px"})

    import webbrowser
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{port}")

    app.run(port=port, debug=False, use_reloader=False)
