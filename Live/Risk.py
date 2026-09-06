"""Pre-trade risk validation — kill switch, equity gate, sizing, short cap."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_KILL = _ROOT / ".hercules" / "kill-switch.json"


@dataclass
class RiskState:
    initial_equity: float
    current_equity: float
    available_equity: float | None = None
    max_drawdown_pct: float = 0.20  # halt if equity drops 20% from initial
    open_shorts: int = 0
    max_concurrent_shorts: int = 5
    blocked: bool = False
    block_reason: str = ""


def _portfolio() -> dict:
    with (_ROOT / "SharedData" / "Portfolio.toml").open("rb") as f:
        return tomllib.load(f)


def kill_active(path: Path | None = None) -> bool:
    path = path or _KILL
    if not path.exists():
        return False
    try:
        state = json.loads(path.read_text())
        return True if not isinstance(state, dict) else bool(state.get("active", False))
    except (json.JSONDecodeError, OSError, TypeError):
        return True


def size_trade(
    equity_usdt: float,
    asset: str,
    *,
    portfolio: dict | None = None,
    risk: dict | None = None,
) -> float:
    """Return USDT notional for one trade on `asset`."""
    pf = portfolio or _portfolio()
    weight = float(pf.get("allocation", {}).get(asset, 0.0))
    params = risk or pf
    trade_pct = float(params.get("trade_size_pct", pf.get("trade_size_pct", 0.30)))
    leverage = float(params.get("leverage", pf.get("leverage", 1.0)))
    return equity_usdt * weight * trade_pct * leverage


def check_entry(
    state: RiskState,
    side: str,  # "LONG" | "SHORT"
    asset: str,
    amount_usdt: float,
    required_margin_usdt: float | None = None,
) -> tuple[bool, str]:
    """Return (allowed, reason). Reason empty when allowed."""
    if state.blocked:
        return False, f"risk blocked: {state.block_reason}"

    if kill_active():
        return False, "kill switch active"

    drawdown = (state.initial_equity - state.current_equity) / max(state.initial_equity, 1e-9)
    if drawdown >= state.max_drawdown_pct:
        state.blocked = True
        state.block_reason = f"max drawdown {drawdown:.1%}"
        return False, state.block_reason

    if amount_usdt < 1.0:
        return False, f"amount too small: {amount_usdt:.2f} USDT"

    margin = amount_usdt if required_margin_usdt is None else required_margin_usdt
    available = state.current_equity if state.available_equity is None else state.available_equity
    if margin > available:
        return False, f"insufficient available equity: need {margin:.2f}, have {available:.2f} USDT"

    if side == "SHORT" and state.open_shorts >= state.max_concurrent_shorts:
        return False, f"max concurrent shorts reached ({state.max_concurrent_shorts})"

    return True, ""


def on_entry(state: RiskState, side: str) -> None:
    if side == "SHORT":
        state.open_shorts += 1


def on_exit(state: RiskState, side: str) -> None:
    if side == "SHORT" and state.open_shorts > 0:
        state.open_shorts -= 1


def update_equity(state: RiskState, new_equity: float, available_equity: float | None = None) -> None:
    state.current_equity = new_equity
    state.available_equity = available_equity
