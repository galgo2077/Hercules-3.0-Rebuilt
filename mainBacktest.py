"""Backtest entry point — loads config, runs engine, shows TUI."""
from SharedParams.Config import load
from Backtest.Engine import run as run_backtest


def main() -> None:
    config = load()
    run_backtest(config)


if __name__ == "__main__":
    main()
