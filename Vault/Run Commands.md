---
project: Hercules 3.0 Rebuilt
type: runbook
status: current
updated: 2026-09-06
---

# Run Commands

```bash
# API plus configured account workers
uv run python Main.py

# deterministic checked-in-data backtest
uv run python mainBacktest.py

# user/account administration
uv run python CreateAccount.py
uv run python setup_demo_account.py

# RDMA parameter search; --apply writes only a candidate passing all limits
uv run python -m Backtest.Tuner --report Backtest/.tuning-runs/lane-1.json
uv run python -m Backtest.TuneSelector --report-dir Backtest/.tuning-runs

# explicit testnet order test; this places testnet orders
uv run python field_test_orders.py
```

See [[Setup]] and [[Test Commands]].
