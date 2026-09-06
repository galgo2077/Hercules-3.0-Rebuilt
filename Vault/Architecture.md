---
project: Hercules 3.0 Rebuilt
type: architecture
status: stabilized
updated: 2026-09-06
---

# Architecture

## Canonical flow

`OHLCV → Frame.build → Strategy.decide(target state) → Risk.size_trade → execution adapter → refreshed state`

- Signals mean target state: `1=LONG`, `-1=SHORT`, `0=hold current state`.
- Reversals close and confirm the opposite side before opening the target side.
- `Live/Execution.py` owns Binance quantity normalization, entry, exit, protection, and emergency close.
- Demo and Real share one lifecycle; Real changes only REST/WebSocket endpoints.
- Paper uses the same frame, decision, sizing, risk, and protection parameters with an in-memory fill adapter.
- Backtest uses the same frame, decision, sizing, and protection configuration against checked-in OHLCV.

## State ownership

| State | Owner |
|---|---|
| Strategy target | `Strategy/Strategy.py` + Rust `_strategy` |
| Sizing/leverage | `Live/Risk.size_trade` |
| Exchange position | Binance, refreshed by `PositionTracker.fetch` |
| Hedge-side mapping | `(symbol, position_side)` in `Live/Positions.py` |
| Worker ownership | atomic PostgreSQL `acquire_worker_lease` RPC |
| User ownership | Supabase RLS plus API account predicates |
| Kill state | `.hercules/kill-switch.json`, parsed by `Live/Risk.kill_active` |

See [[Data Flow]], [[Defect Map]], and [[Failure Points]].
