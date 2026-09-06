---
project: Hercules 3.0 Rebuilt
type: defect-map
status: repaired
updated: 2026-09-06
---

# Defect Map

| Severity/type | Defect and root cause | Files fixed | Regression evidence |
|---|---|---|---|
| Critical/trading | WebSocket symbol was normalized twice | `Live/Execution.py`, `Demo.py`, `Paper.py` | exact/malformed stream tests |
| Critical/security | Trade delete trusted ID under service role | `Live/Server.py` | user A/user B delete tests |
| Critical/trading | Leverage multiplied in sizing and order layers | `Live/Risk.py`, `Execution.py`, `Runner.py` | exact long/short quantity tests |
| Critical/correctness | Entry branch skipped opposite-side close | `Strategy/Strategy.py`, Rust `build.rs`, `Demo.py` | both reversal directions and close-before-open tests |
| Critical/data | Equity/positions/risk were cached startup state | `Demo.py`, `Positions.py`, `Risk.py` | refresh-before-decision/order tests |
| Critical/compatibility | Frame/backtest imported absent old repository | `Dataframe/Frame.py`, `Backtest/Runner.py` | clean install and full checked-in-data E2E |
| High/correctness | Paper mode was never routed | `Worker.py`, `Main.py` | explicit mode-selection tests |
| High/trading | Real skipped hedge initialization | `Real.py`, `Demo.py` | safe mocked real listener test |
| High/data | LONG/SHORT rows overwrote by symbol | `Positions.py`, `Reconcile.py`, `schema.sql` | simultaneous hedge mapping test |
| High/security | Corrupt kill JSON enabled trading | `Risk.py`, `Server.py` | text/array/scalar/unreadable tests |
| High/trading | Protection failure left position open | `Execution.py`, `Orders/Long.py`, `Short.py` | rejected SL/TP emergency-close tests |
| High/trading | Symbol-wide cancel removed opposite hedge protection | `Execution.py` | side-specific order cancellation test |
| High/numerical | Fixed decimal rounding ignored exchange filters | `_client.py`, `Execution.py` | step/minimum/NaN quantity tests |
| High/concurrency | Lease used check-then-set | `Worker.py`, `schema.sql` | single atomic RPC test |
| High/security | Worker leases lacked RLS | `schema.sql` | schema policy test |
| High/security | Stored fields used `innerHTML`; tokens used browser storage | `dashboard/*.js`, `Auth.py`, `AuthRouter.py` | static dashboard security and cookie tests |
| Medium/data | Schema policies failed on rerun; timestamp used literal `now()` | `schema.sql`, `Repos.py` | rerunnable-policy/timestamp tests |
| Medium/API | Interval buttons did not reach candle API | `dashboard/monitor.js`, `Server.py` | endpoint interval validation test |
| Medium/performance | Blocking work ran in async routes | `Server.py`, `DashboardData.py` | sync-route inspection tests |
| Medium/security | Credential env names differed; malformed metadata escaped | `.env.example`, `Crypto.py` | key/metadata/tamper tests |
| Medium/compatibility | Python 3.14 allowed although PyO3 0.24 rejects it | `pyproject.toml`, `uv.lock`, CI | clean Python 3.13 build and Rust tests |
| Medium/correctness | Duplicate closed candles scheduled repeated tasks | `CandleBuffer.py`, `Demo.py` | dedup and task-ownership tests |
| Medium/trading | Missing entry price fell back to stale ticker | `Execution.py` | invalid-price emergency-close test |
| Critical/trading | Timed-out entry confirmation could leave a fill naked | `Execution.py` | missing-confirmation emergency-close test |
| High/trading | Submitted protection was not confirmed | `Execution.py` | unconfirmed-protection emergency-close test |
| High/data | Restart reconciliation missed exchange-only positions | `Reconcile.py` | empty-local/exchange-open test |
| High/data | Refreshed exchange/paper state was not persisted | `Demo.py`, `Paper.py`, `Worker.py`, `Repos.py` | both-side snapshot persistence test |
| High/correctness | Older replayed candles could trigger decisions | `CandleBuffer.py` | monotonic timestamp test |
| High/numerical | Protection prices used nearest-tick rounding | `_client.py`, `Execution.py` | direction-aware SL/TP tests |
| Medium/maintainability | Tuner mutated unused legacy thresholds | `Tuner.py`, `AutoTune.toml`, `Strategy.toml`, `Frame.py` | candidate changes consumed RDMA field |
| Low/quality | Lint/type/Rust formatting errors | affected Python/Rust/test files and CI | Ruff pass, BasedPyright 0, cargo fmt/clippy pass |

Original symptom list, root causes, fixes, affected files, and remaining limits are now represented here and in [[Known Risks]].
