"""Backtest parity gate — 7 trades, same assets/sides as golden baseline."""
import pytest

# Golden baseline (Phase 1): 7 trades, all wins
_GOLDEN = [
    ("BTCUSDT", "long"),
    ("BTCUSDT", "short"),
    ("ETHUSDT", "short"),
    ("SOLUSDT", "short"),
    ("SOLUSDT", "long"),
    ("XRPUSDT", "long"),
    ("XRPUSDT", "short"),
]


@pytest.mark.slow
def test_trade_count():
    from Backtest.Runner import run
    result = run()
    assert result.trades.height == 7, f"expected 7 trades, got {result.trades.height}"


@pytest.mark.slow
def test_all_wins():
    from Backtest.Runner import run
    result = run()
    outcomes = result.trades["outcome"].to_list()
    assert all(o == "win" for o in outcomes), f"non-win outcomes: {outcomes}"


@pytest.mark.slow
def test_asset_side_pairs():
    from Backtest.Runner import run
    result = run()
    trades = result.trades.sort(["asset", "timestamp"]).select(["asset", "side"])
    pairs = [(r["asset"], r["side"]) for r in trades.iter_rows(named=True)]
    golden_sorted = sorted(_GOLDEN)
    assert sorted(pairs) == golden_sorted
