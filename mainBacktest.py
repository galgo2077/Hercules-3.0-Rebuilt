"""Backtest entry point — runs engine, shows TUI progress and results."""
from SharedParams.Config import load
from Backtest.Runner import run
from Backtest.Tui import BacktestProgress, print_results


def main() -> None:
    config = load()
    bt = config.backtest

    with BacktestProgress(bt.assets) as progress:
        result = run(
            start=bt.start_date,
            end=bt.end_date,
            assets=bt.assets,
            initial_cash=bt.initial_cash,
            progress=progress.update,
        )

    print_results(result)


if __name__ == "__main__":
    main()
