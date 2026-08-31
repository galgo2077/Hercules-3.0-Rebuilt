"""Read-only latest-candle strategy readiness for the monitor."""

from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import Any
import tomllib


_ROOT = Path(__file__).resolve().parents[1]
_CACHE: tuple[float, list[dict[str, Any]]] = (0.0, [])


def build(assets: list[str]) -> list[dict[str, Any]]:
    """Classify the latest executable live-strategy candle; this never places orders."""
    global _CACHE
    cached_at, cached = _CACHE
    if monotonic() - cached_at < 60:
        return cached
    mode = tomllib.loads((_ROOT / "SharedData" / "Live.toml").read_text()).get("mode", "demo")
    try:
        import polars as pl
        from Dataframe.Frame import build as build_frame
        from Dataframe.OhlcvCache import fetch_warmup
        from Strategy.Strategy import evaluate

        with (_ROOT / "SharedData" / "Live.toml").open("rb") as f:
            interval = tomllib.load(f).get("interval", "1h")
        frame = build_frame(fetch_warmup(assets, interval, 600))
        decisions = evaluate(frame)
        rows: list[dict[str, Any]] = []
        for asset in assets:
            asset_rows = decisions.filter(pl.col("asset") == asset).sort("timestamp")
            if asset_rows.is_empty():
                continue
            row = asset_rows.tail(1).to_dicts()[0]
            signal = int(row.get("final_signal") or 0)
            allowed = bool(row.get("entry_allowed")) and row.get("action") == "Entry"
            state = "green" if allowed else "yellow" if signal else "red"
            reason = (
                str(row.get("reason") or "No entry signal").replace("_", " ")
                if signal
                else "No entry signal"
            )
            rows.append({"asset": asset, "state": state, "signal": signal, "entry_allowed": allowed, "reason": reason, "timestamp": str(row.get("timestamp") or ""), "mode": mode})
    except Exception as exc:  # dashboard must remain available if market data is unavailable
        rows = [{"asset": asset, "state": "red", "signal": 0, "entry_allowed": False, "reason": f"Readiness unavailable: {str(exc)[:90]}", "timestamp": "", "mode": mode} for asset in assets]
    _CACHE = (monotonic(), rows)  # ponytail: global 60s cache; per-user cache only if dashboard load grows.
    return rows
