"""Backtest parity gate for the current Portfolio and Strategy configuration."""

from collections import Counter

import pytest

_TRADE_COUNT = 310
_ASSET_SIDE_COUNTS = {
    ("BTCUSDT", "long"): 36,
    ("BTCUSDT", "short"): 37,
    ("ETHUSDT", "long"): 27,
    ("ETHUSDT", "short"): 21,
    ("SOLUSDT", "long"): 20,
    ("SOLUSDT", "short"): 16,
    ("XRPUSDT", "long"): 76,
    ("XRPUSDT", "short"): 77,
}


@pytest.mark.slow
def test_trade_count():
    from Backtest.Runner import run

    result = run()
    assert result.trades.height == _TRADE_COUNT


@pytest.mark.slow
def test_all_outcomes_resolved():
    from Backtest.Runner import run

    result = run()
    assert set(result.trades["outcome"].to_list()) <= {"win", "lose"}


@pytest.mark.slow
def test_asset_side_pairs():
    from Backtest.Runner import run

    result = run()
    pairs = result.trades.select(["asset", "side"]).iter_rows()
    assert Counter(pairs) == _ASSET_SIDE_COUNTS
