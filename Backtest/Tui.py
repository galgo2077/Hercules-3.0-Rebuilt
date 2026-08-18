"""Terminal backtest dashboard matching Hercules 3.0."""

from __future__ import annotations

import curses
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType

import polars as pl
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from Backtest.Runner import BacktestResult

_con = Console()


class BacktestProgress:
    """Hercules 3.0 per-asset backtest progress display."""

    def __init__(self, assets: list[str]) -> None:
        self._assets = assets
        self._progress = Progress(
            TextColumn("[bold cyan]Progress[/] {task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            refresh_per_second=12,
        )
        self._tasks: dict[str, TaskID] = {}

    def __enter__(self) -> "BacktestProgress":
        self._progress.__enter__()
        for asset in self._assets:
            self._tasks[asset] = self._progress.add_task(asset, total=100)
        return self

    def update(self, asset: str, fraction: float) -> None:
        tid = self._tasks.get(asset)
        if tid is not None:
            self._progress.update(tid, completed=fraction * 100)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._progress.__exit__(exc_type, exc_value, traceback)


@dataclass(frozen=True, slots=True)
class DashboardView:
    name: str
    frame: pl.DataFrame
    columns: tuple[str, ...]
    context: str = ""
    filter_assets: bool = True
    percentage_columns: tuple[str, ...] = ()
    twin: DashboardView | None = None
    color_thresholds: tuple[tuple[str, float], ...] = ()


def _add(screen: curses.window, y: int, x: int, text: str, style: int = 0) -> None:
    height, width = screen.getmaxyx()
    if 0 <= y < height and 0 <= x < width:
        try:
            screen.addnstr(y, x, text, max(0, width - x - 1), style)
        except curses.error:
            pass


def _display(value: object, width: int, percentage: bool = False) -> str:
    if value is None:
        text = "null"
    elif percentage and isinstance(value, float):
        text = f"{value:.2%}"
    elif isinstance(value, float):
        text = f"{value:.2f}"
    else:
        text = str(value)
    return text[: width - 1].ljust(width)


class BacktestDashboard:
    """Curses table navigator from the Hercules 3.0 backtest TUI."""

    def __init__(
        self,
        screen: curses.window,
        title: str,
        views: list[DashboardView],
        on_open: Callable[[], None] | None = None,
    ) -> None:
        self.screen, self.title, self.views = screen, title, views
        self.on_open = on_open
        self.view_index = self.asset_index = self.column = self._pane_focus = 0
        self.row = self._latest_row()
        self._twin_row = self._twin_column = 0
        self._opening_chart = False
        self._chart_message = ""

    @property
    def view(self) -> DashboardView:
        return self.views[self.view_index]

    @property
    def assets(self) -> list[str]:
        if "asset" not in self.view.frame.columns or not self.view.filter_assets:
            return ["ALL"]
        return self.view.frame["asset"].unique().sort().to_list() or ["ALL"]

    @property
    def frame(self) -> pl.DataFrame:
        if "asset" not in self.view.frame.columns or not self.view.filter_assets:
            return self.view.frame
        asset = self.assets[min(self.asset_index, len(self.assets) - 1)]
        return self.view.frame if asset == "ALL" else self.view.frame.filter(pl.col("asset") == asset)

    def _latest_row(self) -> int:
        return max(0, self.frame.height - 1)

    def run(self) -> None:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.screen.keypad(True)
        self.screen.timeout(100)
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            for pair, color in enumerate((curses.COLOR_CYAN, curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_BLACK, curses.COLOR_RED), 1):
                curses.init_pair(pair, color, curses.COLOR_YELLOW if pair == 4 else -1)
        while True:
            self.draw()
            key = self.screen.getch()
            if key in (ord("q"), 27):
                return
            if key != -1:
                self.handle(key)

    def handle(self, key: int) -> None:
        page = max(1, self.screen.getmaxyx()[0] - 15)
        twin = self.view.twin
        on_twin = twin is not None and self._pane_focus == 1
        if on_twin:
            if twin is None:
                raise RuntimeError("secondary table focus without a secondary table")
            target = twin.frame
        else:
            target = self.frame
        if key == ord("o") and self.on_open is not None and not self._opening_chart:
            self._open_chart()
        elif key == ord("w") and twin:
            self._pane_focus = 0
        elif key == ord("s") and twin:
            self._pane_focus = 1
        elif key in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE, curses.KEY_HOME, curses.KEY_END):
            current = self._twin_row if on_twin else self.row
            limit = max(0, target.height - 1)
            delta = {curses.KEY_UP: -1, curses.KEY_DOWN: 1, curses.KEY_PPAGE: -page, curses.KEY_NPAGE: page}.get(key)
            value = 0 if key == curses.KEY_HOME else limit if key == curses.KEY_END else max(0, min(limit, current + (delta or 0)))
            if on_twin:
                self._twin_row = value
            else:
                self.row = value
        elif key in (curses.KEY_LEFT, curses.KEY_RIGHT):
            columns = twin.columns if on_twin and twin else self.view.columns
            value = max(0, min(len(columns) - 1, (self._twin_column if on_twin else self.column) + (-1 if key == curses.KEY_LEFT else 1)))
            if on_twin:
                self._twin_column = value
            else:
                self.column = value
        elif key in (9, ord("t"), curses.KEY_BTAB, ord("T")):
            step = -1 if key in (curses.KEY_BTAB, ord("T")) else 1
            self.view_index = (self.view_index + step) % len(self.views)
            self.asset_index = self.column = self._pane_focus = self._twin_row = self._twin_column = 0
            self.row = self._latest_row()
        elif key in (ord("["), ord("]"), ord("a")):
            self.asset_index = (self.asset_index + (-1 if key == ord("[") else 1)) % len(self.assets)
            self.row = self._latest_row()

    def _open_chart(self) -> None:
        callback = self.on_open
        if callback is None:
            return
        self._opening_chart = True
        self._chart_message = "Opening chart visualizer…"

        def launch() -> None:
            try:
                callback()
                self._chart_message = "Chart visualizer opened."
            except (ImportError, ModuleNotFoundError) as exc:
                self._chart_message = f"Chart unavailable: {exc}"
            except (OSError, RuntimeError, ValueError) as exc:
                self._chart_message = f"Chart failed: {exc}"
            finally:
                self._opening_chart = False

        threading.Thread(target=launch, daemon=True, name="backtest-visualizer").start()

    def _draw_table(self, frame: pl.DataFrame, view: DashboardView, columns: tuple[str, ...], y0: int, height: int, selected: int, column: int) -> None:
        width = self.screen.getmaxyx()[1]
        cell_width, visible = 18, max(1, (width - 3) // 18)
        start = min(column, max(0, len(columns) - visible))
        shown = columns[start : start + visible]
        for offset, name in enumerate(shown):
            _add(self.screen, y0, offset * cell_width, name[: cell_width - 1].ljust(cell_width), curses.A_BOLD | curses.color_pair(1))
        row_start = min(max(0, selected - height // 2), max(0, frame.height - height))
        thresholds = dict(view.color_thresholds)
        for offset, index in enumerate(range(row_start, min(frame.height, row_start + height))):
            values = frame.row(index, named=True)
            for col_offset, name in enumerate(shown):
                style = curses.A_BOLD if index == selected else 0
                value = values[name]
                if name in thresholds and isinstance(value, (int, float)):
                    style |= curses.color_pair(2 if value > thresholds[name] else 5 if value < thresholds[name] else 0)
                if index == selected and col_offset == column - start:
                    style |= curses.color_pair(4)
                _add(self.screen, y0 + 1 + offset, col_offset * cell_width, _display(value, cell_width, name in view.percentage_columns), style)

    def draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 20 or width < 90:
            _add(self.screen, 0, 0, "Terminal too small — use at least 90×20.", curses.A_BOLD)
            self.screen.refresh()
            return
        frame, twin = self.frame, self.view.twin
        table_height = max(3, height - 10)
        _add(self.screen, 0, 0, self.title, curses.A_BOLD | curses.color_pair(1))
        _add(self.screen, 0, width - 28, "o chart   q quit", curses.A_DIM)
        _add(self.screen, 1, 0, " ".join(f"[{v.name}]" if v is self.view else v.name for v in self.views), curses.A_BOLD)
        asset = self.assets[min(self.asset_index, len(self.assets) - 1)]
        hint = f"Asset [{asset}]  ↑↓/Pg rows  ←→ cols  Tab view  [ ] asset  o chart"
        if twin:
            hint += "  w/s pane"
        if self.view.context:
            hint += f"  |  {self.view.context}"
        _add(self.screen, 2, 0, hint)
        if self._chart_message:
            _add(self.screen, 3, 0, self._chart_message, curses.A_DIM)
        if twin:
            top = max(2, (table_height - 1) // 2)
            bottom = max(2, table_height - top - 1)
            self._draw_table(frame, self.view, self.view.columns, 5, top, self.row if self._pane_focus == 0 else -1, self.column)
            _add(self.screen, 6 + top, 0, "─" * max(0, width - len(twin.name) - 4) + f" ▶ {twin.name} ", curses.color_pair(1))
            self._draw_table(twin.frame, twin, twin.columns, 7 + top, bottom, self._twin_row if self._pane_focus == 1 else -1, self._twin_column)
        else:
            self._draw_table(frame, self.view, self.view.columns, 5, table_height, self.row, self.column)
        self.screen.refresh()


def _results_views(result: BacktestResult) -> list[DashboardView]:
    results = result.results
    if results.is_empty():
        return [DashboardView("Results", results, tuple(results.columns), filter_assets=False)]
    total = results.filter(pl.col("asset") == "TOTAL")
    rows = results.filter(pl.col("asset") != "TOTAL").unique(subset=["asset"], keep="first", maintain_order=True)
    if "win_rate" in rows.columns:
        rows = rows.sort("win_rate", descending=True)
    sorted_results = pl.concat([rows, total.unique(subset=["asset"], keep="first", maintain_order=True)])
    columns = [column for column in sorted_results.columns if column not in ("start", "end")]
    percent = tuple(column for column in ("roi", "buy_and_hold_roi", "max_drawdown", "win_rate", "win_longs_pct", "win_shorts_pct", "nlb&h_roi") if column in columns)
    pnl = tuple(column for column in ("asset", "win_rate", "win_longs_pct", "win_shorts_pct", "end_money", "roi", "roi_usd", "max_drawdown", "max_drawdown_usd") if column in columns)
    risk = tuple(column for column in columns if column not in set(pnl) - {"asset"})
    thresholds = tuple((column, threshold) for column, threshold in (("roi", 0.0), ("roi_usd", 0.0), ("max_drawdown", 0.0), ("max_drawdown_usd", 0.0), ("win_rate", 0.5), ("win_longs_pct", 0.5), ("win_shorts_pct", 0.5)) if column in columns)
    context = f"Range: {results['start'][0]} to {results['end'][0]} | Drawdown: realized PnL ordered by exit time" if {"start", "end"} <= set(results.columns) else ""
    twin = DashboardView("Results", sorted_results, pnl, context, False, percent, color_thresholds=thresholds)
    return [DashboardView("Results Risk", sorted_results, risk, context, False, percent, twin, thresholds)]
def print_results(result: BacktestResult) -> None:
    """Show the Hercules 3.0 table dashboard with on-demand chart visualizer."""
    views = _results_views(result)
    views.extend(DashboardView(name, frame, tuple(frame.columns), filter_assets=False) for name, frame in (("Trades", result.trades), ("Strategy", result.strategy), ("Equity", result.equity)))
    if sys.stdin.isatty() and sys.stdout.isatty():
        def open_visualizer() -> None:
            from Backtest.Visualizator import launch_visualizer
            launch_visualizer(result.strategy, result.trades, result.equity, results=result.results)
        curses.wrapper(lambda screen: BacktestDashboard(screen, "BACKTEST EXPLORER", views, open_visualizer).run())
        return
    _con.print("BACKTEST EXPLORER: interactive TUI requires a terminal")
    for view in views:
        _con.print(f"{view.name}: {view.frame.shape}")
        _con.print(view.frame.select(list(view.columns)).tail(8))
