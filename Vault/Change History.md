---
project: Hercules 3.0 Rebuilt
type: change-history
status: active
updated: 2026-09-06
---

# Change History

## 2026-09-06 — Full stabilization

- Replaced the missing old-repository bridges with local deterministic frame and backtest implementations.
- Defined target-position signal semantics and deterministic bidirectional reversals.
- Centralized sizing and Binance order execution; added exchange-filter quantity handling, confirmed fills, side-specific protection cancellation, and emergency close.
- Made exchange state refresh authoritative for live equity, positions, exposure, and short limits.
- Routed paper/testnet/real explicitly and made Real reuse Demo lifecycle with production endpoints.
- Made worker leasing atomic and added RLS; made schema policies rerunnable.
- Enforced user-scoped trade deletion and account queries.
- Moved browser authentication to HttpOnly strict cookies; removed unsafe DOM rendering and remote scripts; added CSP and cross-origin mutation rejection.
- Restricted Python to 3.12–3.13 for PyO3 0.24 compatibility and removed the unused `json5` dependency.
- Removed legacy indicator thresholds that the self-contained pipeline could not use; tuner now changes RDMA parameters used by `Frame.build`.
- Added regression, integration, parity, failure, dashboard, security, worker, and order tests.
- Migrated Binance protective exits to the current USD-M algo-order API and made the field test derive notional from live exchange filters.
- Probed production Supabase without exposing data; confirmed core RLS isolation and identified missing paper/lease schema deployment.

Rollback: revert the logical stabilization commits listed by `git log` in reverse order.
