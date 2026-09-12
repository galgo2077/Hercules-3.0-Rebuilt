"""FastAPI server — REST API + dashboard for Hercules live engine."""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from Live.Auth import AuthUser, require_auth
from Live.Risk import kill_active
from SharedParams.Config import HerculesConfig

_ROOT = Path(__file__).resolve().parents[1]
_KILL_SWITCH = _ROOT / ".hercules" / "kill-switch.json"
_STATIC = _ROOT / "dashboard"


def _records(data: object) -> list[dict]:
    return [dict(row) for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _owned_account_ids(user_id: str) -> list[str]:
    """Return account IDs belonging to one authenticated user."""
    from SharedParams.Supabase import get_service_client

    response = get_service_client().table("exchange_accounts").select("id").eq("user_id", user_id).execute()
    return [str(row["id"]) for row in _records(response.data) if row.get("id")]


def _security_cfg() -> dict:
    with (_ROOT / "SharedData" / "Security.toml").open("rb") as f:
        return tomllib.load(f)


def _write_kill(active: bool, user_id: str | None = None) -> None:
    _KILL_SWITCH.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"active": active}
    if user_id:
        payload["by"] = user_id
    fd, temp_name = tempfile.mkstemp(dir=_KILL_SWITCH.parent, prefix="kill-", text=True)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, _KILL_SWITCH)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _build_app() -> FastAPI:
    sec = _security_cfg()
    app = FastAPI(title="Hercules", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sec.get("allowed_origins", []),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sec.get("allowed_hosts", ["*"]))

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # noqa: ANN001
        origin = request.headers.get("origin")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin and origin not in sec.get("allowed_origins", []):
            return Response(status_code=status.HTTP_403_FORBIDDEN, content="cross-origin mutation denied")
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    from Live.AccountsRouter import router as accounts_router
    from Live.AuthRouter import router as auth_router

    app.include_router(auth_router)
    app.include_router(accounts_router)

    return app


def _mount_static(application: FastAPI) -> None:
    """Mount dashboard SPA last — after all API routes — so /api/* is never shadowed."""
    if _STATIC.exists():
        application.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="static")


app = _build_app()

_User = Annotated[AuthUser, Depends(require_auth)]


# ── Status ────────────────────────────────────────────────────────────────────


@app.get("/api/status")
def status_endpoint(user: _User) -> dict[str, Any]:
    kill = kill_active(_KILL_SWITCH)
    return {"ok": True, "kill_switch": kill, "user": user.id}


@app.get("/api/config")
def get_config(user: _User) -> dict[str, Any]:
    from SharedParams.Config import load

    cfg = load()
    return {
        "portfolio": {"weights": cfg.portfolio.weights, "leverage": cfg.portfolio.leverage},
        "backtest": {"start": cfg.backtest.start_date, "end": cfg.backtest.end_date, "assets": cfg.backtest.assets},
        "server": {"host": cfg.server.host, "port": cfg.server.port, "mode": cfg.server.mode},
    }


@app.get("/api/dashboard")
def get_dashboard(user: _User, account: str | None = None) -> dict[str, Any]:
    """Return the monitor's read-only, user-scoped aggregate data."""
    from Live.DashboardData import build_dashboard
    from SharedParams.Config import load

    if account is not None and account not in _owned_account_ids(user.id):
        raise HTTPException(status_code=404, detail="account not found")
    cfg = load()
    return build_dashboard(user.id, cfg.portfolio.leverage, cfg.backtest.assets, account)


@app.get("/api/databases")
def list_databases(user: _User) -> list[dict[str, Any]]:
    """Compatibility endpoint: expose user accounts as selectable databases."""
    from SharedParams.Supabase import get_service_client

    response = get_service_client().table("exchange_accounts").select("id,label,environment").eq("user_id", user.id).execute()
    return [{"id": row["id"], "label": row.get("label", ""), "environment": row.get("environment", "testnet")} for row in _records(response.data) if row.get("id")]


@app.get("/api/assets")
def list_assets(user: _User) -> list[str]:
    """Return configured and observed assets for the authenticated user."""
    from SharedParams.Config import load
    from SharedParams.Supabase import get_service_client

    cfg = load()
    client = get_service_client()
    accounts = client.table("exchange_accounts").select("id").eq("user_id", user.id).execute()
    observed: set[str] = set()
    for account in _records(accounts.data):
        response = client.table("trades").select("asset").eq("account_id", account["id"]).execute()
        observed.update(str(row["asset"]) for row in _records(response.data) if row.get("asset"))
    return sorted({*cfg.backtest.assets, *observed})


@app.get("/api/stats")
def get_stats(user: _User, account: str | None = None) -> dict[str, Any]:
    """Compatibility endpoint exposing the monitor statistics object."""
    from Live.DashboardData import build_dashboard
    from SharedParams.Config import load

    if account is not None and account not in _owned_account_ids(user.id):
        raise HTTPException(status_code=404, detail="account not found")
    cfg = load()
    return build_dashboard(user.id, cfg.portfolio.leverage, cfg.backtest.assets, account)["stats"]


@app.get("/accounts", include_in_schema=False)
def accounts_page() -> FileResponse:
    """Serve account selector page before SPA fallback can shadow the route."""
    page = _STATIC / "accounts.html"
    if not page.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="accounts page unavailable")
    return FileResponse(page)


@app.get("/vendor/plotly.min.js", include_in_schema=False)
def plotly_javascript() -> FileResponse:
    import plotly

    source = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
    return FileResponse(source, media_type="application/javascript")


# ── Trades ────────────────────────────────────────────────────────────────────


@app.get("/api/trades")
def list_trades(user: _User, limit: int = 50) -> list[dict]:
    from SharedParams.Supabase import get_service_client

    if not 1 <= limit <= 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
    client = get_service_client()
    return [trade for account_id in _owned_account_ids(user.id) for trade in _records(client.table("trades").select("*").eq("account_id", account_id).order("entry_time", desc=True).limit(limit).execute())][:limit]


@app.delete("/api/trades/{trade_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trade(trade_id: int, user: _User) -> None:
    from SharedParams.Supabase import get_service_client

    client = get_service_client()
    owned = set(_owned_account_ids(user.id))
    response = client.table("trades").select("id,account_id").eq("id", trade_id).execute()
    rows = _records(response.data)
    if not rows or str(rows[0].get("account_id")) not in owned:
        raise HTTPException(status_code=404, detail="trade not found")
    client.table("trades").delete().eq("id", trade_id).eq("account_id", rows[0]["account_id"]).execute()


# ── Positions ─────────────────────────────────────────────────────────────────


@app.get("/api/positions")
def get_positions(user: _User) -> list[dict]:
    from SharedParams.Supabase import get_service_client

    client = get_service_client()
    return [position for account_id in _owned_account_ids(user.id) for position in _records(client.table("live_positions").select("*").eq("account_id", account_id).execute())]


# ── Equity ────────────────────────────────────────────────────────────────────


@app.get("/api/equity")
def get_equity(user: _User, limit: int = 200) -> list[dict]:
    from SharedParams.Supabase import get_service_client

    if not 1 <= limit <= 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
    client = get_service_client()
    rows = [point for account_id in _owned_account_ids(user.id) for point in _records(client.table("equity_snapshots").select("*").eq("account_id", account_id).order("ts", desc=True).limit(limit).execute())]
    return list(reversed(rows[:limit]))


# ── Candles ───────────────────────────────────────────────────────────────────


@app.get("/api/candles")
def get_candles(user: _User, asset: str = "BTCUSDT", limit: int = 200, interval: str = "1h") -> list[dict]:
    from datetime import datetime, timedelta, timezone

    from Dataframe.Binance import INTERVAL_MS, fetch_historical
    from Dataframe.Frame import build

    if not 1 <= limit <= 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    from SharedParams.Config import load

    cfg = load()
    asset = asset.upper()
    if asset not in cfg.backtest.assets:
        raise HTTPException(status_code=400, detail="unsupported asset")
    if interval not in {"1m", "5m", "15m", "1h", "4h", "1d"}:
        raise HTTPException(status_code=400, detail="unsupported interval")
    end = datetime.now(timezone.utc)
    start = end - timedelta(milliseconds=INTERVAL_MS[interval] * limit)
    df = fetch_historical([asset], start.isoformat(), end.isoformat(), interval=interval)
    return build(df).tail(limit).to_dicts()


# ── Kill switch ───────────────────────────────────────────────────────────────


@app.get("/api/kill")
def kill_status(user: _User) -> dict[str, bool]:
    return {"active": kill_active(_KILL_SWITCH)}


@app.post("/api/kill/activate")
def kill_activate(user: _User) -> dict[str, str]:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    _write_kill(True, user.id)
    return {"status": "activated"}


@app.post("/api/kill/reset")
def kill_reset(user: _User) -> dict[str, str]:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    _write_kill(False)
    return {"status": "reset"}


# ── Backtest ──────────────────────────────────────────────────────────────────


@app.get("/api/backtest")
def run_backtest_endpoint(user: _User, asset: str = "BTCUSDT") -> dict[str, Any]:
    import polars as pl

    from Backtest.Runner import run
    from Backtest.Visualizator.app import _asset_figure

    golden = json.loads((_ROOT / "Vault" / "golden_baseline.json").read_text(encoding="utf-8"))
    config = golden["config"]
    asset = asset.upper()
    if asset not in config["assets"]:
        raise HTTPException(status_code=400, detail="unsupported asset")
    strategy = run(start=config["start"], end=config["end"], assets=config["assets"], initial_cash=100.0).strategy
    trades = pl.DataFrame(golden["trades"]).with_columns(pl.col("timestamp", "exit_timestamp").str.to_datetime(time_zone="UTC"))
    asset_strategy = strategy.filter(pl.col("asset") == asset).sort("timestamp")
    asset_trades = trades.filter(pl.col("asset") == asset)
    figure = _asset_figure(strategy, trades, asset)
    x_range = list(figure.layout.xaxis.range or ())
    visible = asset_strategy.filter(pl.col("timestamp") <= x_range[-1]) if x_range else asset_strategy
    return {
        "asset": asset,
        "source": "golden-baseline",
        "traces": [trace.to_plotly_json() for trace in figure.data],
        "x_range": x_range,
        "y_range": list(figure.layout.yaxis.range or ()),
        "last": visible.tail(1).to_dicts()[0],
        "trade_count": asset_trades.height,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

# Mount SPA last so all /api/* routes registered above are never shadowed.
_mount_static(app)


def main(config: HerculesConfig) -> None:
    uvicorn.run(app, host=config.server.host, port=config.server.port, log_level="info")
