"""Strategy module tester — offline, no Binance calls. Print PASS/FAIL with values."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

passed = 0
total = 0


def check(label, got, expected, cmp=None):
    global passed, total
    total += 1
    ok = cmp(got, expected) if cmp else got == expected
    tag = "[PASS]" if ok else "[FAIL]"
    print(f"{tag} {label}: got={got!r} expected={expected!r}")
    if ok:
        passed += 1


# ── 1. import _strategy ────────────────────────────────────────────────────────
try:
    import _strategy
    has_input = hasattr(_strategy, "StrategyInput")
    has_eval = hasattr(_strategy, "evaluate")
    has_build = hasattr(_strategy, "build_decision")
    check("_strategy import StrategyInput", has_input, True)
    check("_strategy import evaluate",      has_eval,  True)
    check("_strategy import build_decision", has_build, True)
except Exception as e:
    print(f"[FAIL] _strategy import: {e}")
    total += 3
    print(f"\n{passed}/{total} passed")
    sys.exit(1)

# ── helpers ────────────────────────────────────────────────────────────────────
def inp(slope=0.1, warmup=True, signal=1, direction="BULLISH"):
    return _strategy.StrategyInput(
        timestamp_ms=0,
        asset="BTCUSDT",
        direction=direction,
        final_signal=signal,
        short_trend_similarity=0.8,
        slope=slope,
        warmup_complete=warmup,
    )

def near(a, b): return abs(a - b) < 1e-9

# ── 2. evaluate — long entry ───────────────────────────────────────────────────
ls, ss = _strategy.evaluate(inp(), 0, True)
check("evaluate long entry long_score",  ls, 1.0, near)
check("evaluate long entry short_score", ss, 0.0, near)

# ── 3. evaluate — no reentry same side ────────────────────────────────────────
ls, ss = _strategy.evaluate(inp(), 1, True)
check("evaluate no reentry long_score",  ls, 0.0, near)
check("evaluate no reentry short_score", ss, 0.0, near)

# ── 4. evaluate — slope gate blocks long with negative slope ──────────────────
ls, ss = _strategy.evaluate(inp(slope=-0.05), 0, True)
check("evaluate neg slope gate long_score", ls, 0.0, near)

# ── 5. evaluate — warmup not complete ─────────────────────────────────────────
ls, ss = _strategy.evaluate(inp(warmup=False), 0, True)
check("evaluate warmup=False long_score",  ls, 0.0, near)
check("evaluate warmup=False short_score", ss, 0.0, near)

# ── 6. build_decision — entry long ────────────────────────────────────────────
r = _strategy.build_decision(0, "BTCUSDT", 1.0, 0.0, 0.0, 0.15, 0.15)
check("build_decision entry long action",        r.action,        "Entry")
check("build_decision entry long side",          r.side,          "Long")
check("build_decision entry long entry_allowed", r.entry_allowed, True)

# ── 7. build_decision — hold flat ─────────────────────────────────────────────
r = _strategy.build_decision(0, "BTCUSDT", 0.0, 0.0, 0.0, 0.15, 0.15)
check("build_decision hold flat action", r.action, "Hold")

# ── 8. Strategy.py load ───────────────────────────────────────────────────────
try:
    from Strategy.Strategy import evaluate as strat_eval
    check("Strategy.py import evaluate", callable(strat_eval), True)
except Exception as e:
    print(f"[FAIL] Strategy.py import: {e}")
    total += 1

# ── summary ───────────────────────────────────────────────────────────────────
print(f"\n{passed}/{total} passed")
