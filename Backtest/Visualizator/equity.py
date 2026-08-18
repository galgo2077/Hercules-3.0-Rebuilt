"""Downsampled interactive equity figure."""

from __future__ import annotations

import plotly.graph_objects as go
import polars as pl

_COLORS = ("#4fc3f7", "#2ecc71", "#f39c12", "#9b59b6", "#ffffff")
_MAX_POINTS = 300


def build_equity_figure(curves: pl.DataFrame) -> go.Figure:
    """Build Hercules-style return curves while limiting browser payload size."""
    traces: list[go.Scattergl] = []
    assets = curves["asset"].unique().sort().to_list()
    assets = [asset for asset in assets if asset != "TOTAL"] + (["TOTAL"] if "TOTAL" in assets else [])
    for index, asset in enumerate(assets):
        curve = curves.filter(pl.col("asset") == asset).sort("timestamp")
        if curve.height > _MAX_POINTS:
            curve = curve.gather_every(max(2, curve.height // _MAX_POINTS))
        initial = float(curve["equity"][0])
        roi = ((curve["equity"] / initial) - 1.0) * 100.0
        traces.append(
            go.Scattergl(
                x=curve["timestamp"].to_list(), y=roi.to_list(), mode="lines", name=asset,
                line={"color": _COLORS[index % len(_COLORS)], "width": 3 if asset == "TOTAL" else 2},
                hovertemplate=f"{asset}: %{{y:.2f}}%<br>%{{x|%Y-%m-%d %H:%M}}<extra></extra>",
            )
        )
    figure = go.Figure(data=traces)
    figure.update_layout(
        template="plotly_dark", uirevision="equity", title="Equity — " + ", ".join(assets),
        xaxis_title="Date", yaxis={"title": "Return (%)", "ticksuffix": "%"}, hovermode="x unified",
        legend={"orientation": "h", "y": 1.08}, margin={"l": 70, "r": 40, "t": 90, "b": 60},
    )
    return figure
