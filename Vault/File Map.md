---
project: Hercules 3.0 Rebuilt
type: file-map
status: current
updated: 2026-09-06
---

# File Map

| Area | Sources of truth | Responsibility |
|---|---|---|
| Entrypoints | `Main.py`, `mainBacktest.py` | live service and backtest startup |
| Market data | `Dataframe/Binance.py`, `CandleBuffer.py`, `Frame.py`, `OhlcvCache.py` | fetch, validate, buffer, and build deterministic signals |
| Strategy | `Strategy/Strategy.py`, `Strategy/Rust/src/core.rs`, `build.rs` | target-position decisions and transition semantics |
| Backtest | `Backtest/Runner.py`, `Tuner.py`, `AutoTune.toml` | deterministic simulator and RDMA parameter search |
| Execution | `Live/Execution.py`, `Demo.py`, `Real.py`, `Paper.py` | shared order rules and mode adapters |
| State/risk | `Live/Positions.py`, `Risk.py`, `Reconcile.py` | side-aware snapshots, sizing, limits, reconciliation |
| Coordination | `Live/Worker.py`, `Main.py` | account engine lifecycle and leases |
| API/auth | `Live/Server.py`, `Auth.py`, `AuthRouter.py`, `AccountsRouter.py` | authenticated, user-scoped HTTP boundary |
| Dashboard | `dashboard/index.html`, `monitor.js`, `login.js`, `accounts.js` | safe DOM rendering and controls |
| Storage | `Storage/schema.sql`, `Storage/Repos.py` | PostgreSQL/RLS schema and worker persistence helpers |
| Configuration | `SharedData/*.toml`, `.env.example` | portfolio, strategy, modes, security, setup |
| Validation | `tests/`, `.github/workflows/ci.yml` | unit/integration/E2E/security/parity gates |

Detailed error-to-file mapping: [[Defect Map]].
