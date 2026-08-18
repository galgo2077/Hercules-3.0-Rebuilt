from __future__ import annotations

from SharedParams.Supabase import get_client, get_service_client


# ── trades ──────────────────────────────────────────────────────────────────

def insert_trade(
    account_id: str,
    asset: str,
    side: str,
    entry_time: str,
    entry_price: float,
    quantity: float,
) -> int:
    row = {
        "account_id": account_id,
        "asset": asset,
        "side": side,
        "entry_time": entry_time,
        "entry_price": entry_price,
        "quantity": quantity,
        "outcome": "open",
    }
    res = get_service_client().table("trades").insert(row).execute()
    return res.data[0]["id"]


def close_trade(
    trade_id: int,
    exit_time: str,
    exit_price: float,
    pnl: float,
    fee: float,
    outcome: str,
) -> None:
    get_service_client().table("trades").update({
        "exit_time": exit_time,
        "exit_price": exit_price,
        "pnl": pnl,
        "fee": fee,
        "outcome": outcome,
    }).eq("id", trade_id).execute()


def list_trades(account_id: str, limit: int = 50) -> list[dict]:
    res = (
        get_client()
        .table("trades")
        .select("*")
        .eq("account_id", account_id)
        .order("entry_time", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data


# ── equity_snapshots ─────────────────────────────────────────────────────────

def upsert_equity(account_id: str, ts: str, equity_usdt: float) -> None:
    # unique constraint on (account_id, ts) — upsert merges on conflict
    get_service_client().table("equity_snapshots").upsert({
        "account_id": account_id,
        "ts": ts,
        "equity_usdt": equity_usdt,
    }, on_conflict="account_id,ts").execute()


def list_equity(account_id: str, limit: int = 200) -> list[dict]:
    res = (
        get_client()
        .table("equity_snapshots")
        .select("*")
        .eq("account_id", account_id)
        .order("ts", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data


# ── live_positions ────────────────────────────────────────────────────────────

def upsert_position(
    account_id: str,
    asset: str,
    side: str,
    size_usdt: float,
    entry_price: float,
) -> None:
    get_service_client().table("live_positions").upsert({
        "account_id": account_id,
        "asset": asset,
        "side": side,
        "size_usdt": size_usdt,
        "entry_price": entry_price,
        # updated_at has DEFAULT now() but upsert won't refresh it automatically
        "updated_at": "now()",
    }, on_conflict="account_id,asset").execute()


def clear_position(account_id: str, asset: str) -> None:
    get_service_client().table("live_positions").delete().eq(
        "account_id", account_id
    ).eq("asset", asset).execute()


def list_positions(account_id: str) -> list[dict]:
    res = (
        get_client()
        .table("live_positions")
        .select("*")
        .eq("account_id", account_id)
        .execute()
    )
    return res.data
