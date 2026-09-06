---
project: Hercules 3.0 Rebuilt
type: data-flow
status: current
updated: 2026-09-06
---

# Data Flow

## Trading

1. `Main.py` loads accounts and `AccountWorker` atomically acquires each lease.
2. Environment selects Paper, Demo/testnet, or Real; credential failures are isolated per account.
3. Closed, validated, deduplicated candles enter `CandleBuffer`.
4. `Frame.build` produces local RDMA direction/signal columns.
5. `Strategy.decide` maps signal plus authoritative exposure to a target position.
6. `Risk.size_trade` calculates leveraged notional once and checks fresh equity/margin limits.
7. Reversal closes and confirms the old side; shared execution opens the new side and confirms SL/TP.
8. Demo/Real refresh account and hedge-side positions after every mutation.

## Backtest and paper

Both consume the same frame, decision, sizing, and protection configuration. Backtest uses checked-in candles and deterministic fees/slippage; Paper uses in-memory virtual fills.

## Browser/API

Login and refresh tokens are HttpOnly SameSite-strict cookies. Server routes validate them through Supabase, scope every resource to owned accounts, and render browser data only through safe DOM text APIs. Plotly is served from the installed local package.

## Storage

PostgreSQL owns account/trade/equity/side-aware position/lease records. RLS enforces user ownership and a restricted security-definer RPC owns atomic lease acquisition.
