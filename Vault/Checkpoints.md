# Hercules 3.0 Rebuild — Checkpoints

## PHASE 0 — Repository and Environment Discovery
**Status:** COMPLETE
**Date:** 2026-08-18
**Branch:** development (no commits yet)

---

### Objective
Full baseline discovery of both repos before any implementation.

### Repos
| Repo | Path | Git State |
|---|---|---|
| Original (READ-ONLY) | `/home/void/Documents/Hercules 3.0` | Active, multiple commits |
| Rebuild (WRITE) | `/home/void/Documents/hercules 3.0 rebuilt` | 0 commits, development branch |

---

### Original Architecture — File Tree (key)
```
Hercules 3.0/
├── run.py                        # entry: opens browser, calls server.main()
├── cli.py                        # CLI wrapper
├── add_user.py                   # user creation utility
├── pyproject.toml                # Python 3.12, setuptools, uv
├── Backtest/
│   ├── Engine/                   # 11 files: backtester, equity_curve, signal_*, statistics, synthetic_market
│   ├── TUI/                      # dashboard.py, monte_carlo.py
│   ├── Visualizator/             # app.py, equity.py, monte_carlo.py, save.py
│   ├── tuning/                   # run_asset.py
│   ├── params.json5              # Backtest config
│   └── run.py                    # Backtest entry
├── Dataframe/
│   └── MariaAPI/maria_api.py     # Binance REST OHLCV fetcher (misleading name)
├── Strategy/
│   ├── strategy.py               # Main strategy assembler
│   ├── params.json5              # Strategy conditions config
│   ├── assets/BTCUSDT|ETHUSDT|XRPUSDT|SOLUSDT|PAXGUSDT/params.json5  # Per-asset tuning
│   ├── trend/                    # RDMA, slope, detector, state_machine, strength, alignment, market_structure
│   ├── volatility/               # ATR, Bollinger, CloseReturn, GarmanKlass, Parkinson, YangZhang, regimes
│   ├── indicators/               # mean_reversion/, noise/, volume/, signal/, pipeline.py
│   └── getData.py
├── live/
│   ├── __main__.py
│   ├── auth/                     # errors, models, password (argon2), rbac, sessions
│   ├── crypto/                   # AES-GCM credential encryption
│   ├── exchanges/                # binance_http, binance_usdtm, binance_usdtm_parsers, fake
│   ├── execution/                # engine, order_manager, position_manager, partitioning, reconciliation, state_machine, strategy_gateway, runtime_pipeline
│   ├── market_data/              # binance_usdtm (REST), binance_usdtm_ws (WebSocket), candle_builder
│   ├── monitoring/Dashboard/     # FastAPI server, API routes, static HTML, auth, users_api, accounts_api, security
│   ├── risk/                     # equity, sizing, portfolios, quantity
│   ├── storage/                  # SQLite via aiosqlite, migrations, repositories, codec
│   └── workers/                  # coordinator, account_worker
└── shared/
    ├── params_assets.json5       # Shared Backtest+Live params (leverage, sizing, weights, exit)
    ├── short_trailing_stop.py
    └── signal_transition.py
```

---

### LOC Baseline
| Scope | LOC |
|---|---|
| Total Python (no venv/cache) | ~30,000 |
| Production-only (no test files) | ~18,629 |
| Target rebuild production LOC | ≤10,000 |

---

### Database — CRITICAL CORRECTION
**Prompt says "PostgreSQL" → actual storage is SQLite (aiosqlite)**

- Runtime DB: `.hercules/live.sqlite3` (SQLite via aiosqlite)
- asyncpg is in pyproject.toml but NOT imported anywhere → dead dependency
- Tables: audit_records, bot_state, asset_state, operational_blocks, current_positions, current_orders, known_fills, current_balances, reconciliation_runs, reconciliation_mismatches, account_leases
- Migration destination: Supabase Cloud (PostgreSQL)
- Strategy: copy schema → adapt to Supabase/PostgreSQL → migrate data

---

### Dependency Inventory
| Package | Status | Keep in Rebuild |
|---|---|---|
| aiosqlite | Active (SQLite runtime storage) | NO — migrate to Supabase |
| argon2-cffi | Active (password hashing) | NO — migrate to Supabase Auth |
| asyncpg | UNUSED (dead dep, 0 imports) | NO |
| cryptography | Active (AES-GCM credential encryption) | YES |
| dash | Active (backtest Visualizator) | EVALUATE |
| fastapi[standard] | Active (server) | YES |
| httpx | Active (HTTP client) | YES |
| json5 | Active (config loading) | NO — migrate to TOML |
| numpy | Active (strategy calculations) | EVALUATE |
| polars | Active (core dataframe) | YES |
| polars-talib | Active (TA indicators) | YES |
| rich | Active (TUI) | YES |
| websockets | Active (Binance WS) | YES |
| plotly | Active (charts) | YES |
| playwright | Active (testing?) | EVALUATE |
| google-auth* | Active (scripts only) | EVALUATE |

---

### Configuration Files — All JSON5
| File | Owner |
|---|---|
| Strategy/params.json5 | Strategy conditions/gates |
| Strategy/assets/BTCUSDT/params.json5 | BTC tuning |
| Strategy/assets/ETHUSDT/params.json5 | ETH tuning |
| Strategy/assets/XRPUSDT/params.json5 | XRP tuning |
| Strategy/assets/SOLUSDT/params.json5 | SOL tuning |
| Strategy/assets/PAXGUSDT/params.json5 | PAXG tuning (not in rebuild spec) |
| Strategy/trend/params.json5 | RDMA/trend params |
| Strategy/volatility/params.json5 | Volatility params |
| Strategy/indicators/mean_reversion/params.json5 | MR indicator params |
| Strategy/indicators/noise/params.json5 | Noise indicator params |
| Strategy/indicators/volume/params.json5 | Volume indicator params |
| Strategy/indicators/signal/params.json5 | Signal/scoring params |
| Backtest/params.json5 | Backtest-only settings |
| Backtest/Visualizator/params.json5 | Visualizator settings |
| shared/params_assets.json5 | Shared Backtest+Live params |

---

### Current Portfolio Weights (shared/params_assets.json5)
| Asset | Current | Target (Rebuild spec) |
|---|---|---|
| BTC | 0.60 (60%) | 0.40 (40%) |
| ETH | 0.10 (10%) | 0.20 (20%) |
| SOL | 0.20 (20%) | 0.20 (20%) |
| XRP | 0.10 (10%) | 0.20 (20%) |

**Weights will change in rebuild — user authorized by spec.**

---

### Current Shared Params (shared/params_assets.json5)
| Param | Value |
|---|---|
| leverage | 15 (global default) |
| trade_size_percentage | 0.30 |
| take_profit_pct | 0.025 |
| checkpoint_trail_pct | 0.012 |
| short_trailing_stop_pct | 0.015 |
| stop_loss_pct | null |
| short_exit_on_bullish_trend | true |
| max_concurrent_shorts | 5 |

**Note:** BTC asset params override leverage=8.0, trade_size_percentage=0.15, stop_loss_pct=0.06

---

### Infrastructure
| Component | Details |
|---|---|
| Server | FastAPI + uvicorn, port 8765, host 127.0.0.1 |
| Cloudflare | Tunnel → 127.0.0.1:8765, systemd service |
| GUI | 4 static HTML pages: index.html, login.html, accounts.html, 404.html |
| Charts | Plotly (embedded in HTML), Dash (Visualizator) |
| Auth | Custom argon2 + cookie sessions + CSRF + RBAC |
| Credentials | AES-GCM encrypted Binance API keys in SQLite |
| Exchange | Binance USDⓈ-M Futures (fapi / demo-fapi) |
| DB | SQLite .hercules/live.sqlite3 |
| Docker | Dockerfile present, python:3.12-slim, exposes 8765 |

---

### Endpoint Inventory (Original)
| Route | Method | Auth |
|---|---|---|
| /api/monitoring | GET | admin |
| /api/managed-accounts | GET | auth |
| /api/auth/login | POST | none |
| /api/auth/logout | POST | auth |
| /api/databases | GET | auth |
| /api/status | GET | auth |
| /api/stats | GET | auth |
| /api/backtest | GET | auth |
| /api/config | GET | auth |
| /api/assets | GET | auth |
| /api/candles | GET | auth |
| /api/trades | GET | auth |
| /api/trades/{id} | DELETE | auth |
| /api/kill | GET | auth |
| /api/kill/activate | POST | admin |
| /api/kill/reset | POST | admin |
| /api/test/long-short | POST | admin |
| /accounts | GET | auth |
| / | GET | auth |
| /login | GET | none |
| /{path} | GET | auth |
| + accounts_api routes | | |
| + user_routes | | |
| + terminal_log_routes | | |
| + recovery_routes | | |

---

### Strategy Architecture (Original)
```
Binance REST (MariaAPI)
  ↓
Polars DataFrame (OHLCV)
  ↓
volatility.py → regimes.py
trend.py (RDMA fast/medium/slow → slope → detector → state_machine)
indicators/pipeline.py (mean_reversion + noise + volume + signal)
  ↓
strategy.py (build_strategy_dataframe)
  ↓
final_signal (buy/sell/none)
  ↓
live/execution/strategy_gateway.py
  ↓
live/execution/engine.py
  ↓
live/exchanges/binance_usdtm.py
```

---

### Rebuild Repo Current State
- Branch: development
- Commits: NONE
- Files: .gitignore only
- Empty folders: Backtest/Engine, Backtest/Tui, Backtest/Visualizator, Dataframe/Binance, Live/Demo, Live/Orders, Live/Server, SharedParams/, Startegy/ (typo — should be Strategy/)

---

### Phase 0 Gate
- [x] Both repos located and confirmed separate
- [x] File tree documented
- [x] LOC measured
- [x] Dependencies inventoried
- [x] Config format documented (all JSON5)
- [x] DB schema documented (SQLite, NOT PostgreSQL)
- [x] Infrastructure documented (Cloudflare tunnel → 8765)
- [x] Endpoints inventoried
- [x] Portfolio weights documented (discrepancy noted)
- [x] Tuning files located
- [x] Strategy architecture mapped
- [x] GUI documented (4 static HTML pages)

**PHASE 0: PASS**

---

### Do-Not-Repeat
- DO NOT modify original repo in any way
- DO NOT use asyncpg (dead dep in original, not needed)
- DB is SQLite → Supabase, not PostgreSQL → Supabase
- Portfolio weights LOCKED to original (user confirmed 2026-08-18): BTC=60%, ETH=10%, SOL=20%, XRP=10%

---

## PHASE 1 — Golden Trading Baseline
**Status:** COMPLETE
**Date:** 2026-08-18

### Objective
Run original Backtest with frozen data/config → deterministic golden reference.

### Config used (frozen)
| Param | Value |
|---|---|
| start_date | 2026-04-01T00:00:00Z |
| end_date | 2026-07-20T00:00:00Z |
| timeframe | 1h |
| assets | BTC, ETH, SOL, XRP |
| initial_cash | 100.0 |
| fee_rate | 0.001 |
| slippage_rate | 0.0005 |

### Golden Trades (7 total)
| Asset | Side | Entry | Exit | Outcome |
|---|---|---|---|---|
| BTCUSDT | long | 2026-04-11 01:00 UTC | 2026-04-14 14:00 UTC | win |
| BTCUSDT | short | 2026-06-03 10:00 UTC | 2026-06-03 21:00 UTC | win |
| ETHUSDT | short | 2026-05-20 19:00 UTC | 2026-05-22 20:00 UTC | win |
| SOLUSDT | short | 2026-06-01 18:00 UTC | 2026-06-02 17:00 UTC | win |
| SOLUSDT | long | 2026-07-08 20:00 UTC | 2026-07-10 02:00 UTC | win |
| XRPUSDT | long | 2026-05-10 21:00 UTC | 2026-05-11 16:00 UTC | win |
| XRPUSDT | short | 2026-06-04 04:00 UTC | 2026-06-04 08:00 UTC | win |

### Golden Results
| Asset | ROI | Win Rate | Trades | Longs | Shorts | Max Drawdown |
|---|---|---|---|---|---|---|
| BTCUSDT | 7.53% | 100% | 2 | 1 | 1 | -3.88% |
| ETHUSDT | 13.14% | 100% | 1 | 0 | 1 | -5.52% |
| SOLUSDT | 31.43% | 100% | 2 | 1 | 1 | -4.35% |
| XRPUSDT | 24.06% | 100% | 2 | 1 | 1 | -3.36% |
| TOTAL | 14.53% | 100% | 7 | 3 | 4 | -2.33% |

### Signal Summary (367 non-zero signal bars from 10,564 total)
| Asset | BUY bars | SELL bars |
|---|---|---|
| BTCUSDT | 101 | 73 |
| ETHUSDT | 79 | 75 |
| SOLUSDT | 17 | 14 |
| XRPUSDT | 3 | 5 |

### Determinism
Run twice, identical results. PASS.

### Files
- `Vault/golden_baseline.json` — full results + trades
- `Vault/golden_sha256.txt` — SHA256: eab7ee5cbf057334bc2db6b3b6c42c00513ebd11ab4028f8fc5547ea8144eb16

### Phase 1 Gate
- [x] Golden baseline captured
- [x] Deterministic (2 runs identical)
- [x] Both Long and Short signals proven
- [x] Both Long and Short trades proven
- [x] All 4 assets generate signals

**PHASE 1: PASS**

---

### Next Phase
**PHASE 2 — Rebuild Minimal Skeleton**
Next step: create Python project (pyproject.toml, uv), Rust crate (Cargo.toml, PyO3/maturin), minimal config loader, root entry points. Fix typo Startegy→Strategy.

### Do-Not-Repeat
- DO NOT modify original repo
- Golden baseline SHA256 is the parity target: eab7ee5cbf057334bc2db6b3b6c42c00513ebd11ab4028f8fc5547ea8144eb16
