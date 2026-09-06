---
project: Hercules 3.0 Rebuilt
type: setup
status: validated
updated: 2026-09-06
---

# Setup

```bash
cd /home/galgo/Documents/Hercules-3.0-Rebuilt
uv python install 3.13
uv sync --locked
cp .env.example .env
```

Populate `.env` locally with Supabase settings and a base64 32-byte `HERCULES_MASTER_KEY`. Binance credentials are encrypted into account records by `setup_demo_account.py`; Paper accounts require none. Apply `Storage/schema.sql` in Supabase before service startup.

Supported Python is 3.12–3.13. Python 3.14 is intentionally rejected by package metadata because the locked PyO3 0.24 toolchain does not support it.
