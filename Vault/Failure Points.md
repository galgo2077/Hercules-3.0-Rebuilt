---
project: Hercules 3.0 Rebuilt
type: failure-points
status: fail-closed
updated: 2026-09-06
---

# Failure Points

| Trigger | Deterministic behavior | Files |
|---|---|---|
| Malformed/missing candle fields | reject candle before buffering | `Dataframe/CandleBuffer.py` |
| Unknown stream/symbol | ignore without dispatch | `Live/Execution.py`, `Live/Demo.py` |
| Invalid/zero quantity | reject before order | `Live/Execution.py` |
| Entry not confirmed or entry price invalid | emergency close or raise severe failure | `Live/Execution.py` |
| SL/TP creation failure | cancel created protection, emergency close, raise | `Live/Execution.py` |
| Reversal close not confirmed | do not open target side | `Live/Demo.py` |
| Both hedge sides unexpectedly open | fail closed on ambiguous net exposure | `Live/Positions.py` |
| Corrupt/unreadable kill state | trading disabled | `Live/Risk.py` |
| Lease held/lost | worker does not start or stops | `Live/Worker.py`, `Storage/schema.sql` |
| Invalid credential/key metadata | reject with normalized error; do not expose detail to dashboard | `Live/Crypto.py`, `Live/DashboardData.py` |
| Cross-user account/trade ID | return not found; no mutation | `Live/Server.py`, `Live/AccountsRouter.py` |
| Cross-origin browser mutation | HTTP 403 | `Live/Server.py` |
| One account fails startup | other workers and API continue | `Main.py` |

See [[Defect Map]] for root causes and regression tests.
