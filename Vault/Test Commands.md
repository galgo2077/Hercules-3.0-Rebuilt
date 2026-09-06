---
project: Hercules 3.0 Rebuilt
type: testing
status: passing
updated: 2026-09-06
---

# Test Commands

```bash
uv sync --locked
uv run ruff check .
uv run basedpyright Backtest Dataframe Live SharedParams Storage Strategy Main.py
uv run pytest -q
cargo fmt --manifest-path Strategy/Rust/Cargo.toml --check
PYO3_PYTHON="$PWD/.venv/bin/python" cargo clippy --manifest-path Strategy/Rust/Cargo.toml --all-targets -- -D warnings
PYO3_PYTHON="$PWD/.venv/bin/python" cargo test --manifest-path Strategy/Rust/Cargo.toml
uv run python -m Dataframe.Tester
uv run python -m Strategy.Tester
```

Latest results: Python `168 passed`; Rust `14 passed`; Ruff pass; BasedPyright `0 errors`; compile/import pass; clean Python 3.13 install pass. PostgreSQL schema execution was not run locally because neither PostgreSQL nor Docker is installed; schema behavior has static regression coverage.
