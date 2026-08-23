"""Select a valid worker result, then validate it on fresh real-candle paths."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from Backtest.Runner import run
from Backtest.Tuner import _ROOT, _apply, _CachedWindowSource, _passes, _paths, _toml, _total


def select(report_dir: Path, *, apply: bool) -> dict:
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(report_dir.glob("lane-*.json"))]
    passed = [report for report in reports if report.get("passed")]
    if not passed:
        return {"applied": False, "reason": "no worker candidate passed its paths", "reports": len(reports)}
    winner = max(passed, key=lambda report: (report["worst_roi_to_drawdown"], report["worst_roi_pct"], report["worst_win_rate"]))
    settings = _toml(_ROOT / "Backtest" / "AutoTune.toml")
    backtest = _toml(_ROOT / "SharedData" / "Backtest.toml")
    validation_search = {**settings["search"], "seed": 999}
    source = _CachedWindowSource()
    metrics = [_total(run(start=start, end=end, strategy_override=winner["strategy"], maria_api=source)) for start, end in _paths(backtest["data"], validation_search)]
    valid = all(_passes(path, settings["constraints"]) for path in metrics)
    if apply and valid:
        _apply(winner["strategy"])
    return {"applied": apply and valid, "valid": valid, "worker_candidate": winner["candidate"], "validation": metrics}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and apply best tuning worker result.")
    parser.add_argument("--report-dir", type=Path, default=_ROOT / "Backtest" / ".tuning-runs")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(select(args.report_dir, apply=args.apply), sort_keys=True))


if __name__ == "__main__":
    main()
