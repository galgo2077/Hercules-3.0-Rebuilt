---
project: Hercules 3.0 Rebuilt
type: dependencies
status: reproducible
updated: 2026-09-06
---

# Dependencies

- Python: `>=3.12,<3.14`; validated with uv Python 3.13.15.
- Native strategy: Rust 2021, PyO3 0.24, Maturin.
- Install: `uv sync --locked` from the checked-in `uv.lock`.
- Historical OHLCV: checked-in `.cache/ohlcv/77d0352d920db4e6902b301a.parquet`.
- Runtime services: Supabase/PostgreSQL and Binance Futures for testnet/real modes.
- No dependency on `/home/void/Documents/Hercules 3.0` or another local repository remains.
- `HERCULES_MASTER_KEY` is the single AES-256-GCM master-key variable.

See `pyproject.toml`, `Strategy/Rust/Cargo.toml`, and `.env.example`.
