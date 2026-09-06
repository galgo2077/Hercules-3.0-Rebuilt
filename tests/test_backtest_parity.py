"""Full checked-in-data acceptance gate for the self-contained backtest."""

import pytest


@pytest.fixture(scope="module")
def result():
    from Backtest.Runner import run

    return run()


@pytest.mark.slow
def test_full_backtest_has_only_resolved_protected_trades(result) -> None:
    assert not result.trades.is_empty()
    assert set(result.trades["outcome"].to_list()) <= {"win", "lose"}
    assert result.trades["exit_price"].null_count() == 0
    assert set(result.trades["exit_reason"].to_list()) <= {"stop_loss", "take_profit", "reversal", "risk_halt", "end_of_test"}


@pytest.mark.slow
def test_full_backtest_results_and_equity_are_complete(result) -> None:
    assert set(result.results["asset"].to_list()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "TOTAL"}
    assert set(result.equity["asset"].unique().to_list()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "TOTAL"}
    assert result.strategy.height > 200_000
    assert {-1, 1} <= set(result.strategy["final_signal"].unique().to_list())
