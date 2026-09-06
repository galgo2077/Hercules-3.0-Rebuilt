"""Self-contained deterministic portfolio backtest."""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import polars as pl

_ROOT = Path(__file__).resolve().parents[1]
ProgressCallback = Callable[[str, float], None]
MonteCarloProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class BacktestResult:
    results: pl.DataFrame
    trades: pl.DataFrame
    strategy: pl.DataFrame
    equity: pl.DataFrame


def _toml(name: str) -> dict[str, Any]:
    with (_ROOT / "SharedData" / f"{name}.toml").open("rb") as handle:
        return tomllib.load(handle)


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _cached_ohlcv(assets: list[str], start: str, end: str, interval: str) -> pl.DataFrame:
    from Dataframe.Binance import INTERVAL_MS, fetch_historical

    end_time = _timestamp(end)
    for source in sorted((_ROOT / ".cache" / "ohlcv").glob("*.parquet"), key=lambda path: path.stat().st_size, reverse=True):
        frame = pl.read_parquet(source)
        time_column = "timestamp" if "timestamp" in frame.columns else "open_time"
        if not {"asset", time_column} <= set(frame.columns) or not set(assets) <= set(frame["asset"].unique().to_list()):
            continue
        timestamps = frame.filter(pl.col("asset") == assets[0]).sort(time_column)[time_column].head(2).to_list()
        if len(timestamps) == 2 and int((timestamps[1] - timestamps[0]).total_seconds() * 1000) != INTERVAL_MS[interval]:
            continue
        latest = [frame.filter(pl.col("asset") == asset)[time_column].max() for asset in assets]
        if any(not isinstance(value, datetime) or value < end_time for value in latest):
            continue
        selected = frame.filter(pl.col("asset").is_in(assets), pl.col(time_column).is_between(_timestamp(start), end_time, closed="both"))
        return selected.rename({time_column: "timestamp"}) if time_column != "timestamp" else selected
    return fetch_historical(assets, start, end, interval=interval)


def _load_ohlcv(
    assets: list[str],
    start: str,
    end: str,
    interval: str,
    source: object | None,
    progress: ProgressCallback | None,
) -> pl.DataFrame:
    if source is None:
        frame = _cached_ohlcv(assets, start, end, interval)
    else:
        getter = getattr(source, "get_dataframe", None)
        if not callable(getter):
            raise TypeError("maria_api must provide get_dataframe()")
        frame = cast(pl.DataFrame, getter(assets, start, end, interval=interval, progress=progress))
        if "timestamp" not in frame.columns and "open_time" in frame.columns:
            frame = frame.rename({"open_time": "timestamp"})
    if frame.is_empty():
        raise ValueError("no OHLCV data for requested backtest range")
    return frame.sort("timestamp", "asset")


def _close_trade(position: dict[str, Any], timestamp: datetime, price: float, reason: str, fee_rate: float, slippage: float) -> tuple[dict[str, Any], float]:
    side = position["side"]
    exit_price = price * (1.0 - slippage if side == "long" else 1.0 + slippage)
    direction = 1.0 if side == "long" else -1.0
    gross = direction * (exit_price - position["open"]) / position["open"] * position["size_usdt"]
    fees = fee_rate * position["size_usdt"] * 2.0
    pnl = gross - fees
    trade = {
        "asset": position["asset"],
        "type": side,
        "side": side,
        "timestamp": position["timestamp"],
        "entry_time": position["timestamp"],
        "open": position["open"],
        "entry_price": position["open"],
        "exit_timestamp": timestamp,
        "exit_price": exit_price,
        "quantity": position["size_usdt"] / position["open"],
        "size_usdt": position["size_usdt"],
        "pnl": pnl,
        "fees": fees,
        "outcome": "win" if pnl > 0 else "lose",
        "exit_reason": reason,
    }
    return trade, pnl


def _metrics(asset: str, trades: list[dict[str, Any]], initial: float, end: float, max_drawdown: float, start: datetime, finish: datetime) -> dict[str, Any]:
    selected = trades if asset == "TOTAL" else [trade for trade in trades if trade["asset"] == asset]
    wins = sum(trade["outcome"] == "win" for trade in selected)
    longs = [trade for trade in selected if trade["side"] == "long"]
    shorts = [trade for trade in selected if trade["side"] == "short"]
    return {
        "asset": asset,
        "start": start,
        "end": finish,
        "number_of_trades": len(selected),
        "win_rate": wins / len(selected) if selected else 0.0,
        "win_longs_pct": sum(trade["outcome"] == "win" for trade in longs) / len(longs) if longs else 0.0,
        "win_shorts_pct": sum(trade["outcome"] == "win" for trade in shorts) / len(shorts) if shorts else 0.0,
        "end_money": end,
        "roi_usd": end - initial,
        "roi": end / initial - 1.0,
        "max_drawdown": max_drawdown,
        "max_drawdown_usd": max_drawdown * initial,
    }


def _simulate(strategy: pl.DataFrame, initial_cash: float, portfolio: dict[str, Any], backtest: dict[str, Any], strategy_config: dict[str, Any]) -> BacktestResult:
    from Live.Risk import size_trade
    from Strategy.Strategy import decide

    rows = strategy.sort("timestamp", "asset").iter_rows(named=True)
    fee_rate = float(backtest["execution"]["fee_rate"])
    slippage = float(backtest["execution"]["slippage_rate"])
    positions: dict[str, dict[str, Any]] = {}
    trades: list[dict[str, Any]] = []
    last_prices: dict[str, float] = {}
    equity_rows: list[dict[str, Any]] = []
    total_equity_rows: list[dict[str, Any]] = []
    strategy_rows: list[dict[str, Any]] = []
    assets = sorted(strategy["asset"].unique().to_list())
    initial_by_asset = {asset: initial_cash * float(portfolio.get("allocation", {}).get(asset, 0.0)) for asset in assets}
    realized_by_asset = {asset: 0.0 for asset in assets}
    cash = initial_cash
    blocked = False
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None

    for row in rows:
        asset = str(row["asset"])
        timestamp = row["timestamp"]
        first_timestamp = first_timestamp or timestamp
        last_timestamp = timestamp
        last_prices[asset] = float(row["close"])
        position = positions.get(asset)
        protective_exit = False
        if position is not None:
            stop = position.get("stop_loss")
            take = position.get("take_profit")
            trigger: tuple[float, str] | None = None
            if position["side"] == "long":
                if stop is not None and float(row["low"]) <= stop:
                    trigger = (stop, "stop_loss")
                elif take is not None and float(row["high"]) >= take:
                    trigger = (take, "take_profit")
            else:
                if stop is not None and float(row["high"]) >= stop:
                    trigger = (stop, "stop_loss")
                elif take is not None and float(row["low"]) <= take:
                    trigger = (take, "take_profit")
            if trigger is not None:
                trade, pnl = _close_trade(position, timestamp, trigger[0], trigger[1], fee_rate, slippage)
                trades.append(trade)
                cash += pnl
                realized_by_asset[asset] += pnl
                positions.pop(asset)
                position = None
                protective_exit = True

        if "action" not in row:
            if protective_exit:
                decision = {
                    "action": "Exit",
                    "side": "None",
                    "target_exposure": 0.0,
                    "exposure_delta": 0.0,
                    "entry_allowed": False,
                    "exit_required": True,
                    "reason": trade["exit_reason"],
                }
            else:
                current_exposure = 0.0 if position is None else (1.0 if position["side"] == "long" else -1.0)
                decision = decide(row, current_exposure, strategy_config=strategy_config, portfolio_config=portfolio)
            row = {**row, **decision}
        strategy_rows.append(row)

        if not blocked and not protective_exit and row.get("action") == "Entry":
            target = "long" if row.get("side") == "Long" else "short"
            if position is not None and position["side"] != target:
                trade, pnl = _close_trade(position, timestamp, float(row["close"]), "reversal", fee_rate, slippage)
                trades.append(trade)
                cash += pnl
                realized_by_asset[asset] += pnl
                positions.pop(asset)
                position = None
            if position is None:
                asset_params = {**portfolio, **strategy_config.get("assets", {}).get(asset, {})}
                size = size_trade(cash, asset, portfolio=portfolio, risk=asset_params)
                raw_price = float(row["close"])
                entry_price = raw_price * (1.0 + slippage if target == "long" else 1.0 - slippage)
                stop_pct = asset_params.get("stop_loss_pct")
                take_pct = asset_params.get("take_profit_pct")
                if stop_pct is None and take_pct is None:
                    raise ValueError(f"no protective exit configured for {asset}")
                positions[asset] = {
                    "asset": asset,
                    "side": target,
                    "timestamp": timestamp,
                    "open": entry_price,
                    "size_usdt": size,
                    "stop_loss": entry_price * (1.0 - float(stop_pct) if target == "long" else 1.0 + float(stop_pct)) if stop_pct is not None else None,
                    "take_profit": entry_price * (1.0 + float(take_pct) if target == "long" else 1.0 - float(take_pct)) if take_pct is not None else None,
                }

        unrealized_total = 0.0
        for open_position in positions.values():
            mark = last_prices.get(open_position["asset"], open_position["open"])
            direction = 1.0 if open_position["side"] == "long" else -1.0
            unrealized_total += direction * (mark - open_position["open"]) / open_position["open"] * open_position["size_usdt"]
        if not blocked and cash + unrealized_total <= initial_cash * 0.80:
            for open_position in list(positions.values()):
                trade, pnl = _close_trade(open_position, timestamp, float(last_prices.get(open_position["asset"]) or open_position["open"]), "risk_halt", fee_rate, slippage)
                trades.append(trade)
                cash += pnl
                realized_by_asset[open_position["asset"]] += pnl
            positions.clear()
            position = None
            blocked = True
            unrealized_total = 0.0

        open_position = positions.get(asset)
        unrealized = 0.0
        if open_position is not None:
            direction = 1.0 if open_position["side"] == "long" else -1.0
            unrealized = direction * (float(row["close"]) - open_position["open"]) / open_position["open"] * open_position["size_usdt"]
        equity_rows.append({"timestamp": timestamp, "asset": asset, "equity": initial_by_asset[asset] + realized_by_asset[asset] + unrealized})
        total_equity_rows.append({"timestamp": timestamp, "asset": "TOTAL", "equity": cash + unrealized_total})

    if first_timestamp is None or last_timestamp is None:
        raise ValueError("strategy produced no rows")
    for position in list(positions.values()):
        trade, pnl = _close_trade(position, last_timestamp, last_prices[position["asset"]], "end_of_test", fee_rate, slippage)
        trades.append(trade)
        cash += pnl
        realized_by_asset[position["asset"]] += pnl

    trade_frame = pl.DataFrame(trades) if trades else pl.DataFrame(schema={"asset": pl.String, "side": pl.String, "outcome": pl.String})
    equity_rows.extend({"timestamp": last_timestamp, "asset": asset, "equity": initial_by_asset[asset] + realized_by_asset[asset]} for asset in assets)
    asset_equity = pl.DataFrame(equity_rows).group_by("timestamp", "asset", maintain_order=True).agg(pl.col("equity").last()).sort("timestamp", "asset")
    total_equity_rows.append({"timestamp": last_timestamp, "asset": "TOTAL", "equity": cash})
    total_equity = pl.DataFrame(total_equity_rows).group_by("timestamp", maintain_order=True).agg(pl.col("asset").last(), pl.col("equity").last())
    equity = pl.concat([asset_equity, total_equity]).sort("timestamp", "asset")

    def drawdown(asset: str) -> float:
        values = equity.filter(pl.col("asset") == asset)["equity"].to_list()
        peak = values[0]
        worst = 0.0
        for value in values:
            peak = max(peak, value)
            worst = min(worst, value / peak - 1.0)
        return worst

    results = [_metrics(asset, trades, initial_by_asset[asset], initial_by_asset[asset] + realized_by_asset[asset], drawdown(asset), first_timestamp, last_timestamp) for asset in assets]
    results.append(_metrics("TOTAL", trades, initial_cash, cash, drawdown("TOTAL"), first_timestamp, last_timestamp))
    return BacktestResult(results=pl.DataFrame(results), trades=trade_frame, strategy=pl.DataFrame(strategy_rows), equity=equity)


def run(
    *,
    start: str | None = None,
    end: str | None = None,
    assets: list[str] | None = None,
    initial_cash: float | None = None,
    strategy_override: dict | None = None,
    maria_api: object | None = None,
    progress: ProgressCallback | None = None,
    monte_carlo_progress: MonteCarloProgressCallback | None = None,
) -> BacktestResult:
    """Build signals and simulate them with repository-owned code only."""
    del monte_carlo_progress
    from Dataframe.Frame import build

    bt = _toml("Backtest")
    portfolio = _toml("Portfolio")
    selected_assets = assets or list(bt["data"]["assets"])
    selected_start = start or str(bt["data"]["start_date"])
    selected_end = end or str(bt["data"]["end_date"])
    ohlcv = _load_ohlcv(selected_assets, selected_start, selected_end, str(bt["data"].get("timeframe", "1h")), maria_api, progress)
    base_strategy = _toml("Strategy")
    strategy_config = strategy_override or base_strategy
    strategy = build(ohlcv, strategy_config=strategy_config)
    return _simulate(strategy, float(initial_cash if initial_cash is not None else bt["capital"]["initial_cash"]), portfolio, bt, strategy_config)
