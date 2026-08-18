"""FastAPI server — REST API + dashboard for Hercules live engine."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from Live.Auth import AuthUser, require_auth
from SharedParams.Config import HerculesConfig

_ROOT = Path(__file__).resolve().parents[1]
_KILL_SWITCH = _ROOT / ".hercules" / "kill-switch.json"


def _security_cfg() -> dict:
    with (_ROOT / "Security.toml").open("rb") as f:
        return tomllib.load(f)


def _build_app() -> FastAPI:
    sec = _security_cfg()
    app = FastAPI(title="Hercules", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sec.get("allowed_origins", []),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sec.get("allowed_hosts", ["*"]))
    return app


app = _build_app()

_User = Annotated[AuthUser, Depends(require_auth)]


# ── Status ────────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def status_endpoint(user: _User) -> dict[str, Any]:
    kill = _KILL_SWITCH.exists() and json.loads(_KILL_SWITCH.read_text()).get("active", False)
    return {"ok": True, "kill_switch": kill, "user": user.id}


@app.get("/api/config")
async def get_config(user: _User) -> dict[str, Any]:
    from SharedParams.Config import load
    cfg = load()
    return {
        "portfolio": {"weights": cfg.portfolio.weights, "leverage": cfg.portfolio.leverage},
        "backtest": {"start": cfg.backtest.start_date, "end": cfg.backtest.end_date, "assets": cfg.backtest.assets},
        "server": {"host": cfg.server.host, "port": cfg.server.port, "mode": cfg.server.mode},
    }


# ── Trades ────────────────────────────────────────────────────────────────────

@app.get("/api/trades")
async def list_trades(user: _User, limit: int = 50) -> list[dict]:
    from SharedParams.Supabase import get_client
    client = get_client()
    resp = (
        client.table("trades")
        .select("*")
        .order("entry_time", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


@app.delete("/api/trades/{trade_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trade(trade_id: int, user: _User) -> None:
    from SharedParams.Supabase import get_client
    get_client().table("trades").delete().eq("id", trade_id).execute()


# ── Candles ───────────────────────────────────────────────────────────────────

@app.get("/api/candles")
async def get_candles(user: _User, asset: str = "BTCUSDT", limit: int = 200) -> list[dict]:
    from Dataframe.Binance import fetch_historical
    from datetime import datetime, timedelta, timezone
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=limit)
    df = fetch_historical([asset], start.isoformat(), end.isoformat())
    return df.to_dicts()


# ── Kill switch ───────────────────────────────────────────────────────────────

@app.get("/api/kill")
async def kill_status(user: _User) -> dict[str, bool]:
    active = _KILL_SWITCH.exists() and json.loads(_KILL_SWITCH.read_text()).get("active", False)
    return {"active": active}


@app.post("/api/kill/activate")
async def kill_activate(user: _User) -> dict[str, str]:
    if user.role not in {"admin", "service_role"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    _KILL_SWITCH.parent.mkdir(parents=True, exist_ok=True)
    _KILL_SWITCH.write_text(json.dumps({"active": True, "by": user.id}))
    return {"status": "activated"}


@app.post("/api/kill/reset")
async def kill_reset(user: _User) -> dict[str, str]:
    if user.role not in {"admin", "service_role"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    if _KILL_SWITCH.exists():
        _KILL_SWITCH.write_text(json.dumps({"active": False}))
    return {"status": "reset"}


# ── Backtest ──────────────────────────────────────────────────────────────────

@app.get("/api/backtest")
async def run_backtest_endpoint(user: _User) -> dict[str, Any]:
    from Backtest.Runner import run
    result = run()
    return {
        "trades": result.trades.to_dicts(),
        "results": result.results.to_dicts(),
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def main(config: HerculesConfig) -> None:
    uvicorn.run(app, host=config.server.host, port=config.server.port, log_level="info")
