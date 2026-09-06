---
project: Hercules 3.0 Rebuilt
type: risk-register
status: validated-with-limitations
updated: 2026-09-06
---

# Known Risks

## Remaining limitations

1. No signed Binance order was sent: the production database contains one testnet account, but `HERCULES_MASTER_KEY` is not available in the local environment. No real account is configured; real-money orders remain intentionally prohibited.
2. Production Supabase is reachable and RLS isolation passed for accounts/trades/equity/positions, but its deployed schema is stale: paper accounts are rejected and the atomic lease RPC is absent. Apply `Storage/schema.sql`, then rerun the two-user and lease tests.
3. Historical output parity with the missing old Hercules repository cannot be proven. Current backtest/demo/paper decision semantics are shared and deterministic.
4. Paper models one net position per asset and does not emulate partial fills, funding, latency, or every exchange rejection. It is strategy-parity simulation, not an exchange emulator.
5. Worker account discovery occurs at process startup; account additions require a service restart before a worker is created.
6. Browser cookies use `secure=false` for localhost. Production deployment must set `secure_cookie=true` behind HTTPS.
7. A Starlette deprecation warning remains in the third-party TestClient compatibility layer; tests pass and no replacement package was added.
8. The production website still serves the older dashboard bundle; authenticated browser testing is blocked because the supplied password is rejected by Supabase Auth.

## Opportunity areas

- Integrate reconciliation/persistence into the worker lifecycle or delete those dormant modules once production requirements are decided.
- Add a PostgreSQL-backed CI service to execute `Storage/schema.sql` twice and test RLS with two authenticated users.
- Add recorded Binance testnet contract tests for conditional-order payloads without risking real funds.
- Refresh the historical OHLCV cache and retune against the current self-contained RDMA parameters.
