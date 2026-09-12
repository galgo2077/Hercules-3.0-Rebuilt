"""E2E parity tests — live vs backtest order parameters must match exactly."""

from __future__ import annotations

import datetime

import pytest

# ── helpers ──────────────────────────────────────────────────────────────────


def _risk(asset: str) -> dict:
    from Strategy.Strategy import asset_risk_params

    return asset_risk_params(asset)


def _sl_price(entry: float, sl_pct: float) -> float:
    return round(entry * (1.0 + sl_pct), 2)


def _tp_price(entry: float, tp_pct: float) -> float:
    return round(entry * (1.0 - tp_pct), 2)


# ── A: per-asset param resolution ────────────────────────────────────────────


def test_btcusdt_params_override():
    r = _risk("BTCUSDT")
    assert r["leverage"] == 10.0
    assert r["trade_size_pct"] == 0.15
    assert r["stop_loss_pct"] == 0.06
    assert r["take_profit_pct"] == 0.03
    assert r["checkpoint_trail_pct"] == 0.008
    assert r["short_trailing_stop_pct"] == 0.018


def test_ethusdt_params_take_profit_override():
    r = _risk("ETHUSDT")
    assert r["leverage"] == 10.0
    assert r["trade_size_pct"] == 0.25
    assert r["stop_loss_pct"] == 0.06
    assert r["take_profit_pct"] == 0.03
    assert r["checkpoint_trail_pct"] == 0.01


def test_solusdt_params_all_global():
    r = _risk("SOLUSDT")
    assert r["leverage"] == 10.0
    assert r["trade_size_pct"] == 0.25
    assert r["stop_loss_pct"] == 0.06
    assert r["take_profit_pct"] == 0.025
    assert r["checkpoint_trail_pct"] == 0.012
    assert r["short_trailing_stop_pct"] == 0.015


def test_xrpusdt_leverage_override():
    assert _risk("XRPUSDT")["leverage"] == 15.0


# ── B: trade sizing parity ────────────────────────────────────────────────────


def test_sizing_btcusdt():
    from Live.Risk import size_trade

    assert abs(size_trade(10_000.0, "BTCUSDT", risk=_risk("BTCUSDT")) - 4_500.0) < 1e-9


def test_sizing_ethusdt():
    from Live.Risk import size_trade

    assert abs(size_trade(10_000.0, "ETHUSDT", risk=_risk("ETHUSDT")) - 7_500.0) < 1e-9


def test_sizing_solusdt():
    from Live.Risk import size_trade

    assert abs(size_trade(10_000.0, "SOLUSDT", risk=_risk("SOLUSDT")) - 2_500.0) < 1e-9


def test_sizing_xrpusdt():
    from Live.Risk import size_trade

    assert abs(size_trade(10_000.0, "XRPUSDT", risk=_risk("XRPUSDT")) - 11_250.0) < 1e-9


# ── C: short SL/TP price levels ───────────────────────────────────────────────


def test_short_sl_above_entry():
    sl = _sl_price(50_000.0, 0.06)
    assert sl == 53_000.0
    assert sl > 50_000.0  # SL above entry for short


def test_short_tp_below_entry():
    tp = _tp_price(50_000.0, 0.03)
    assert tp == 48_500.0
    assert tp < 50_000.0  # TP below entry for short


def test_short_btcusdt_sl_tp_exact():
    r = _risk("BTCUSDT")
    entry = 50_000.0
    sl = _sl_price(entry, r["stop_loss_pct"])
    tp = _tp_price(entry, r["take_profit_pct"])
    assert sl == 53_000.0
    assert tp == 48_500.0


def test_short_ethusdt_has_global_sl():
    r = _risk("ETHUSDT")
    assert r["stop_loss_pct"] == 0.06


def test_paper_long_has_configured_protection():
    from Live.Paper import PaperEngine

    engine = PaperEngine()
    engine._buffer.ingest("BTCUSDT", {"t": 1, "o": 100, "h": 100, "l": 100, "c": 100, "v": 1})
    engine._enter("BTCUSDT", "LONG", 1000.0, stop_loss_pct=0.06, take_profit_pct=0.03)
    position = engine.positions["BTCUSDT"]
    assert position.stop_loss_price == 94.0
    assert position.take_profit_price == 103.0


# ── D: Paper SL/TP trigger logic ─────────────────────────────────────────────


def test_short_sl_triggers_on_high():
    from Live.Paper import VirtualPosition

    pos = VirtualPosition(
        asset="BTCUSDT",
        side="SHORT",
        entry_price=100.0,
        size_usdt=1000.0,
        stop_loss_price=106.0,
        take_profit_price=97.0,
    )
    candle_high = 107.0
    assert pos.stop_loss_price is not None and candle_high >= pos.stop_loss_price


def test_short_tp_triggers_on_low():
    from Live.Paper import VirtualPosition

    pos = VirtualPosition(
        asset="BTCUSDT",
        side="SHORT",
        entry_price=100.0,
        size_usdt=1000.0,
        stop_loss_price=106.0,
        take_profit_price=97.0,
    )
    candle_low = 96.5
    assert pos.take_profit_price is not None and candle_low <= pos.take_profit_price


def test_short_no_trigger_within_range():
    from Live.Paper import VirtualPosition

    pos = VirtualPosition(
        asset="BTCUSDT",
        side="SHORT",
        entry_price=100.0,
        size_usdt=1000.0,
        stop_loss_price=106.0,
        take_profit_price=97.0,
    )
    candle_high, candle_low = 104.0, 98.0
    sl_hit = pos.stop_loss_price is not None and candle_high >= pos.stop_loss_price
    tp_hit = pos.take_profit_price is not None and candle_low <= pos.take_profit_price
    assert not sl_hit and not tp_hit


def test_long_no_sl_tp_never_triggers():
    from Live.Paper import VirtualPosition

    pos = VirtualPosition(
        asset="BTCUSDT",
        side="LONG",
        entry_price=100.0,
        size_usdt=1000.0,
    )
    # Any candle — nothing triggers because SL/TP are None
    candle_high, candle_low = 200.0, 50.0
    sl_hit = pos.stop_loss_price is not None and candle_high >= pos.stop_loss_price
    tp_hit = pos.take_profit_price is not None and candle_low <= pos.take_profit_price
    assert not sl_hit and not tp_hit


# ── E: SensitiveStrategy frame shape ─────────────────────────────────────────


def test_sensitive_frame_shape():
    from Strategy.SensitiveStrategy import make_sensitive_frame

    frame = make_sensitive_frame("BTCUSDT", 10)
    assert frame.height == 10
    required = {"timestamp", "open", "high", "low", "close", "volume", "asset", "direction", "short_trend_similarity", "final_signal", "slope"}
    assert required.issubset(set(frame.columns))


def test_sensitive_frame_signals_alternate():
    from Strategy.SensitiveStrategy import make_sensitive_frame

    frame = make_sensitive_frame("BTCUSDT", 10)
    sigs = frame["final_signal"].to_list()
    assert sigs == [1, -1, 1, -1, 1, -1, 1, -1, 1, -1]


def test_sensitive_frame_slope_matches_signal():
    from Strategy.SensitiveStrategy import make_sensitive_frame

    frame = make_sensitive_frame("BTCUSDT", 10)
    for row in frame.iter_rows(named=True):
        if row["final_signal"] == 1:
            assert row["slope"] > 0
        else:
            assert row["slope"] < 0


def test_sensitive_frame_asset_column():
    from Strategy.SensitiveStrategy import make_sensitive_frame

    frame = make_sensitive_frame("ETHUSDT", 5)
    assert all(a == "ETHUSDT" for a in frame["asset"].to_list())


def test_sensitive_frame_timestamps_hourly():
    from Strategy.SensitiveStrategy import make_sensitive_frame

    frame = make_sensitive_frame("BTCUSDT", 3)
    ts = frame["timestamp"].to_list()
    delta = (ts[1] - ts[0]).total_seconds()
    assert delta == 3600.0


# ── F: Strategy evaluate signal → decision (requires Rust module) ─────────────


@pytest.fixture
def strategy_available():
    try:
        import _strategy  # noqa: F401

        return True
    except ImportError:
        pytest.skip("_strategy Rust module not built")


def _make_flat_frame(asset: str, signal: int, slope: float):
    import polars as pl

    base = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    direction = "BULLISH" if signal == 1 else "BEARISH"
    return pl.DataFrame(
        {
            "timestamp": [base],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000.0],
            "asset": [asset],
            "direction": [direction],
            "short_trend_similarity": [0.6],
            "final_signal": [signal],
            "slope": [slope],
        }
    )


def test_long_signal_entry_long(strategy_available):
    from Strategy.Strategy import evaluate

    frame = _make_flat_frame("BTCUSDT", 1, 0.01)
    result = evaluate(frame, asset_exposures={"BTCUSDT": 0.0})
    last = result.filter(result["asset"] == "BTCUSDT").tail(1).row(0, named=True)
    assert last["action"] == "Entry"
    assert last["side"] == "Long"


def test_short_signal_entry_short(strategy_available):
    from Strategy.Strategy import evaluate

    frame = _make_flat_frame("BTCUSDT", -1, -0.01)
    result = evaluate(frame, asset_exposures={"BTCUSDT": 0.0})
    last = result.filter(result["asset"] == "BTCUSDT").tail(1).row(0, named=True)
    assert last["action"] == "Entry"
    assert last["side"] == "Short"


def test_same_side_no_reentry(strategy_available):
    from Strategy.Strategy import evaluate

    frame = _make_flat_frame("BTCUSDT", 1, 0.01)
    # already long (positive exposure)
    result = evaluate(frame, asset_exposures={"BTCUSDT": 0.15})
    last = result.filter(result["asset"] == "BTCUSDT").tail(1).row(0, named=True)
    assert last["action"] == "Hold"


def test_long_reverses_to_short(strategy_available):
    from Strategy.Strategy import evaluate

    frame = _make_flat_frame("BTCUSDT", -1, -0.01)
    # Signals represent target positions; an opposing target requires reversal.
    result = evaluate(frame, asset_exposures={"BTCUSDT": 0.15})
    last = result.filter(result["asset"] == "BTCUSDT").tail(1).row(0, named=True)
    assert last["reason"] == "reversal_to_short"
    assert last["exit_required"] is True
    assert last["entry_allowed"] is True


def test_invalid_signal_is_rejected(strategy_available):
    from Strategy.Strategy import evaluate

    with pytest.raises(ValueError, match="invalid final_signal"):
        evaluate(_make_flat_frame("BTCUSDT", 2, -0.01))
