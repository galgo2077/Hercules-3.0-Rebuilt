"""Rich TUI — live backtest progress and results summary."""
from __future__ import annotations

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn
from rich.table import Table

from Backtest.Runner import BacktestResult

_con = Console()


class BacktestProgress:
    """Context manager: shows per-asset progress bars during backtest run."""

    def __init__(self, assets: list[str]) -> None:
        self._assets = assets
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=30),
            TextColumn("{task.percentage:>3.0f}%"),
            console=_con,
            transient=False,
        )
        self._tasks: dict[str, TaskID] = {}

    def __enter__(self) -> "BacktestProgress":
        self._progress.__enter__()
        for asset in self._assets:
            self._tasks[asset] = self._progress.add_task(asset, total=1.0)
        return self

    def update(self, asset: str, fraction: float) -> None:
        tid = self._tasks.get(asset)
        if tid is not None:
            self._progress.update(tid, completed=fraction)

    def __exit__(self, *exc: object) -> None:
        self._progress.__exit__(*exc)


def print_results(result: BacktestResult) -> None:
    """Print a summary table after backtest completes."""
    if result.results.is_empty():
        _con.print("[yellow]No results.[/yellow]")
        return

    table = Table(title="Backtest Results", show_lines=True)
    for col in result.results.columns:
        table.add_column(col, justify="right")
    for row in result.results.iter_rows(named=True):
        table.add_row(*[str(v) for v in row.values()])
    _con.print(table)

    if not result.trades.is_empty():
        t = Table(title=f"Trades ({result.trades.height})", show_lines=True)
        show = ["asset", "side", "entry_time" if "entry_time" in result.trades.columns else "timestamp",
                "outcome", "pnl"]
        cols = [c for c in show if c in result.trades.columns]
        for col in cols:
            t.add_column(col, justify="right")
        for row in result.trades.iter_rows(named=True):
            t.add_row(*[str(row.get(c, "")) for c in cols])
        _con.print(t)
