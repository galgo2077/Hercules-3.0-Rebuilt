---
project: Hercules 3.0 Rebuilt
type: services
status: current
updated: 2026-09-06
---

# Services

| Service | Purpose | Failure policy |
|---|---|---|
| Supabase Auth/PostgreSQL | users, accounts, RLS, leases, records | reject auth/mutation; isolate failed account workers |
| Binance Futures REST | account state, filters, leverage, orders | no state guess; failed protection triggers emergency close |
| Binance Futures WebSocket | closed kline stream | validate/deduplicate; reconnect with task drain |
| FastAPI/Uvicorn | authenticated API and local dashboard | synchronous external work runs in threadpool routes |
| Rust `_strategy` | deterministic signal-to-target transition | invalid signal rejected |

No process supervisor, container deployment, database migration runner, or external observability service is included.
