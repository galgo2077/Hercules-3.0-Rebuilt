---
project: Hercules 3.0 Rebuilt
type: risk-register
status: validated-with-limitations
updated: 2026-09-06
---

# Known Risks

## Remaining limitations

1. Real Binance orders and funds were not used during validation; real mode was initialized only with mocked non-trading interfaces.
2. Schema execution/rerun was statically validated but not executed against PostgreSQL because no local PostgreSQL/Docker runtime is installed.
3. Historical output parity with the missing old Hercules repository cannot be proven. Current backtest/demo/paper decision semantics are shared and deterministic.
4. Paper models one net position per asset and does not emulate partial fills, funding, latency, or every exchange rejection. It is strategy-parity simulation, not an exchange emulator.
5. Worker account discovery occurs at process startup; account additions require a service restart before a worker is created.
6. Browser cookies use `secure=false` for localhost. Production deployment must set `secure_cookie=true` behind HTTPS.
7. A Starlette deprecation warning remains in the third-party TestClient compatibility layer; tests pass and no replacement package was added.

## Opportunity areas

- Integrate reconciliation/persistence into the worker lifecycle or delete those dormant modules once production requirements are decided.
- Add a PostgreSQL-backed CI service to execute `Storage/schema.sql` twice and test RLS with two authenticated users.
- Add recorded Binance testnet contract tests for conditional-order payloads without risking real funds.
- Refresh the historical OHLCV cache and retune against the current self-contained RDMA parameters.
