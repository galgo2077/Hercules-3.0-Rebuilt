"""Automatic real-candle Monte Carlo tuning with immutable 50% historical paths."""

from __future__ import annotations

import argparse
import json
import random
import re
import time
import tomllib
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from Backtest.Runner import BacktestResult, run

_ROOT = Path(__file__).resolve().parents[1]
_STRATEGY_PATH = _ROOT / "SharedData" / "Strategy.toml"


class _CachedWindowSource:
    """Serve sampled windows from the full local candle cache; never fetch network data."""

    def __init__(self) -> None:
        cache = _ROOT / ".cache" / "ohlcv"
        source = max(cache.glob("*.parquet"), key=lambda path: path.stat().st_size, default=None)
        if source is None:
            raise FileNotFoundError("full historical candle cache is required for auto tuning")
        self._frame = pl.read_parquet(source)

    def get_dataframe(self, assets: list[str], start_date: str, end_date: str, *, interval: str, progress: Any = None) -> pl.DataFrame:
        del interval
        symbols = [asset.upper() for asset in assets]
        frame = self._frame.filter(
            pl.col("asset").is_in(symbols),
            pl.col("open_time").is_between(_timestamp(start_date), _timestamp(end_date), closed="both"),
        )
        if frame.is_empty():
            raise ValueError("sampled path contains no cached candles")
        if progress is not None:
            for asset in symbols:
                progress(asset, 1, 1)
        return frame


def _toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _paths(data: dict[str, Any], search: dict[str, Any]) -> list[tuple[str, str]]:
    start, end = _timestamp(data["start_date"]), _timestamp(data["end_date"])
    duration = end - start
    fraction = float(search["training_fraction"])
    if not 0 < fraction <= 0.5:
        raise ValueError("training_fraction must be greater than 0 and no more than 0.5")
    window = duration * fraction
    generator = random.Random(int(search["seed"]))  # noqa: S311 - reproducible historical sampling
    offsets = [generator.random() * (duration - window) for _ in range(int(search["paths"]))]
    return [
        ((start + offset).isoformat().replace("+00:00", "Z"), (start + offset + window).isoformat().replace("+00:00", "Z"))
        for offset in offsets
    ]


def _candidate(base: dict[str, Any], ranges: dict[str, Any], generator: random.Random) -> dict[str, Any]:
    candidate = deepcopy(base)
    for settings in candidate["assets"].values():
        settings["signal_minimum_overall_confidence"] = round(generator.uniform(ranges["minimum_confidence"], ranges["maximum_confidence"]), 3)
        settings["signal_minimum_signal_score"] = round(generator.uniform(ranges["minimum_score"], ranges["maximum_score"]), 3)
    return candidate


def _total(result: BacktestResult) -> dict[str, float]:
    total = result.results.filter(pl.col("asset") == "TOTAL")
    if total.is_empty():
        raise RuntimeError("backtest did not produce TOTAL metrics")
    row = total.row(0, named=True)
    return {
        "trades": float(row["number_of_trades"]),
        "win_rate": float(row["win_rate"]),
        "roi_pct": float(row["roi"]) * 100,
        "max_drawdown_pct": float(row["max_drawdown"]) * 100,
    }


def _passes(metrics: dict[str, float], limits: dict[str, Any]) -> bool:
    roi_to_drawdown = metrics["roi_pct"] / abs(metrics["max_drawdown_pct"]) if metrics["max_drawdown_pct"] < 0 else float("inf")
    return (
        limits["minimum_total_trades"] <= metrics["trades"] <= limits["maximum_total_trades"]
        and metrics["win_rate"] >= limits["minimum_win_rate"]
        and metrics["roi_pct"] >= limits["minimum_roi_pct"]
        and metrics["max_drawdown_pct"] >= limits["minimum_max_drawdown_pct"]
        and roi_to_drawdown >= limits["minimum_roi_to_drawdown"]
    )


def tune(*, candidates: int | None = None, paths: int | None = None, duration_minutes: int | None = None, seed: int | None = None) -> dict[str, Any]:
    settings = _toml(_ROOT / "Backtest" / "AutoTune.toml")
    backtest = _toml(_ROOT / "SharedData" / "Backtest.toml")
    strategy = _toml(_STRATEGY_PATH)
    source = _CachedWindowSource()
    search = {**settings["search"], **({"candidates": candidates} if candidates else {}), **({"paths": paths} if paths else {}), **({"seed": seed} if seed is not None else {})}
    generator = random.Random(int(search["seed"]))  # noqa: S311 - reproducible parameter search
    minutes = duration_minutes if duration_minutes is not None else int(search.get("duration_minutes", 0))
    if minutes < 0:
        raise ValueError("duration_minutes must not be negative")
    deadline = time.monotonic() + minutes * 60
    best: dict[str, Any] | None = None
    index = 0
    while index < int(search["candidates"]) or time.monotonic() < deadline:
        index += 1
        candidate = _candidate(strategy, settings["ranges"], generator)
        metrics = [_total(run(start=start, end=end, strategy_override=candidate, maria_api=source)) for start, end in _paths(backtest["data"], search)]
        passed = all(_passes(path, settings["constraints"]) for path in metrics)
        ratios = [path["roi_pct"] / abs(path["max_drawdown_pct"]) if path["max_drawdown_pct"] < 0 else float("inf") for path in metrics]
        record = {
            "candidate": index,
            "passed": passed,
            "worst_roi_pct": min(path["roi_pct"] for path in metrics),
            "worst_win_rate": min(path["win_rate"] for path in metrics),
            "worst_drawdown_pct": min(path["max_drawdown_pct"] for path in metrics),
            "worst_roi_to_drawdown": min(ratios),
            "paths": metrics,
            "strategy": candidate,
        }
        if passed and (best is None or (record["worst_roi_pct"], record["worst_win_rate"], record["worst_drawdown_pct"]) > (best["worst_roi_pct"], best["worst_win_rate"], best["worst_drawdown_pct"])):
            best = record
        print(json.dumps({key: record[key] for key in record if key not in {"strategy", "paths"}}, sort_keys=True), flush=True)
    return best or {"passed": False, "reason": "no candidate passed every hard limit"}


def _apply(strategy: dict[str, Any]) -> None:
    text = _STRATEGY_PATH.read_text(encoding="utf-8")
    for asset, values in strategy["assets"].items():
        section = rf"(\[assets\.{re.escape(asset)}\][\s\S]*?)(?=\n\[assets\.|\Z)"
        match = re.search(section, text)
        if match is None:
            raise RuntimeError(f"missing Strategy.toml section for {asset}")
        body = match.group(1)
        for key in ("signal_minimum_overall_confidence", "signal_minimum_signal_score"):
            body = re.sub(rf"({key}\s*=\s*)[0-9.]+", rf"\g<1>{values[key]:.3f}", body)
        text = text[: match.start()] + body + text[match.end() :]
    _STRATEGY_PATH.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune on real 50% historical Monte Carlo paths.")
    parser.add_argument("--candidates", type=int)
    parser.add_argument("--paths", type=int)
    parser.add_argument("--duration-minutes", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true", help="write only a candidate passing every limit")
    args = parser.parse_args()
    result = tune(candidates=args.candidates, paths=args.paths, duration_minutes=args.duration_minutes, seed=args.seed)
    if args.apply and result["passed"]:
        _apply(result["strategy"])
    print(json.dumps({key: value for key, value in result.items() if key not in {"strategy", "paths"}}, sort_keys=True))
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
