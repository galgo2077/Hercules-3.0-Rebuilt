#!/usr/bin/env python3
"""Field test — places real Long + Short (with SL/TP) on Binance TESTNET.

Loads credentials from Supabase exchange_accounts (demo/testnet account).
Cleans up after itself (cancels open orders + closes positions).

Run:
    source .venv/bin/activate
    python field_test_orders.py

Required env vars (same as live engine):
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
    HERCULES_MASTER_KEY
"""

from __future__ import annotations

import sys
import time

_TESTNET = "https://testnet.binancefuture.com"
_SYMBOL = "BTCUSDT"
_LEVERAGE = 1       # leverage=1 → minimal notional exposure
_SL_PCT = 0.03      # 3% SL — tight, just enough to clear testnet tick
_TP_PCT = 0.02      # 2% TP

_pass = 0
_fail = 0


def _ok(label: str, detail: str = "") -> None:
    global _pass
    _pass += 1
    print(f"  [PASS]  {label}" + (f"  ({detail})" if detail else ""))


def _fail_check(label: str, detail: str = "") -> None:
    global _fail
    _fail += 1
    print(f"  [FAIL]  {label}" + (f"  ({detail})" if detail else ""))


def section(title: str) -> None:
    print(f"\n{'─'*64}")
    print(f"  {title}")
    print(f"{'─'*64}")


def _load_demo_creds() -> tuple[str, str, str]:
    """Return (account_id, api_key, api_secret) for the testnet account in Supabase."""
    from SharedParams.Supabase import get_service_client
    from Live.Crypto import load_credential

    db = get_service_client()
    rows = db.table("exchange_accounts").select("id,label,environment").execute().data
    if not rows:
        raise LookupError("No exchange_accounts found in Supabase")

    # Pick the testnet/demo account — prefer environment='testnet', fall back to first
    demo = next((r for r in rows if r.get("environment") == "testnet"), rows[0])
    account_id = demo["id"]
    label = demo.get("label", account_id)
    print(f"  Using account: {label!r}  id={account_id}  env={demo.get('environment')}")

    api_key, api_secret = load_credential(account_id)
    return account_id, api_key, api_secret


def main() -> None:
    section("0 — Load demo credentials from Supabase")
    try:
        account_id, api_key, api_secret = _load_demo_creds()
        _ok("Credentials decrypted from Supabase", f"account={account_id}")
    except Exception as exc:
        _fail_check("Load credentials", str(exc))
        import traceback; traceback.print_exc()
        print("\nCannot continue without credentials.")
        sys.exit(1)

    from Live._client import BinanceClient
    from Live.Orders import Long, Short

    client = BinanceClient(_TESTNET, api_key=api_key, api_secret=api_secret)

    try:
        # ── 1. Hedge mode ─────────────────────────────────────────────────────
        section("1 — Hedge mode")
        client.ensure_hedge_mode()
        resp = client.get("/fapi/v1/positionSide/dual")
        if resp.get("dualSidePosition", False):
            _ok("dualSidePosition=true confirmed")
        else:
            _fail_check("dualSidePosition still false", str(resp))
            print("  Cannot trade without hedge mode — aborting")
            return

        # ── 2. Price + tick size ──────────────────────────────────────────────
        section("2 — Market data")
        price_resp = client.get("/fapi/v1/ticker/price", symbol=_SYMBOL)
        entry_price = float(price_resp["price"])
        tick = client.tick_size(_SYMBOL)
        # Minimum notional on testnet is ~$5; use $6 to stay safely above
        qty = max(0.001, round(6.0 / entry_price, 3))
        print(f"  {_SYMBOL} price : {entry_price:.2f}")
        print(f"  tickSize       : {tick}")
        print(f"  order qty      : {qty}  (~${qty * entry_price:.2f} notional)")
        _ok("Price fetched", f"{entry_price:.2f}")
        _ok("tickSize fetched", str(tick))

        # ── 3. Long entry — no SL, no TP ─────────────────────────────────────
        section("3 — Long entry (no SL, no TP)")
        client.set_leverage(_SYMBOL, _LEVERAGE)
        long_resp = Long.enter(client, _SYMBOL, qty * entry_price, _LEVERAGE)
        print(f"  Binance: {long_resp}")
        if long_resp.get("orderId"):
            _ok("Long MARKET placed", f"orderId={long_resp['orderId']}")
        else:
            _fail_check("Long MARKET — missing orderId", str(long_resp))

        time.sleep(1.0)

        # Confirm position on exchange
        positions = client.get("/fapi/v2/positionRisk")
        long_pos = next((p for p in positions if p["symbol"] == _SYMBOL and p["positionSide"] == "LONG"), None)
        long_amt = float(long_pos["positionAmt"]) if long_pos else 0.0
        if long_amt > 0:
            _ok("Long position confirmed on exchange", f"positionAmt={long_amt}")
        else:
            _fail_check("Long position not visible", f"positionAmt={long_amt}")

        # Confirm NO stop orders placed for long
        open_orders = client.get("/fapi/v1/openOrders", symbol=_SYMBOL)
        long_stops = [o for o in open_orders if o.get("positionSide") == "LONG"
                      and o["type"] in ("STOP_MARKET", "TAKE_PROFIT_MARKET")]
        if not long_stops:
            _ok("Long has zero SL/TP orders (correct)")
        else:
            _fail_check("Long unexpectedly has SL/TP orders", str([o["type"] for o in long_stops]))

        # ── 4. Close Long ─────────────────────────────────────────────────────
        section("4 — Close Long")
        close_long = Long.exit(client, _SYMBOL)
        print(f"  Binance: {close_long}")
        if close_long.get("orderId"):
            _ok("Long exit placed", f"orderId={close_long['orderId']}")
        else:
            _fail_check("Long exit — missing orderId", str(close_long))
        time.sleep(1.0)

        # ── 5. Short entry — with SL + TP ────────────────────────────────────
        section(f"5 — Short entry  (SL={_SL_PCT*100:.0f}%  TP={_TP_PCT*100:.0f}%)")
        short_resp = Short.enter(
            client, _SYMBOL, qty * entry_price, _LEVERAGE,
            stop_loss_pct=_SL_PCT,
            take_profit_pct=_TP_PCT,
        )
        print(f"  Binance entry: {short_resp}")
        if short_resp.get("orderId"):
            _ok("Short MARKET placed", f"orderId={short_resp['orderId']}")
        else:
            _fail_check("Short MARKET — missing orderId", str(short_resp))

        time.sleep(1.0)

        # Confirm short position on exchange
        positions2 = client.get("/fapi/v2/positionRisk")
        short_pos = next((p for p in positions2 if p["symbol"] == _SYMBOL and p["positionSide"] == "SHORT"), None)
        short_amt = abs(float(short_pos["positionAmt"])) if short_pos else 0.0
        if short_amt > 0:
            _ok("Short position confirmed on exchange", f"positionAmt={-short_amt}")
        else:
            _fail_check("Short position not visible", f"positionAmt={short_amt}")

        # Confirm SL and TP orders exist
        open_orders2 = client.get("/fapi/v1/openOrders", symbol=_SYMBOL)
        short_open = [o for o in open_orders2 if o.get("positionSide") == "SHORT"]
        types_found = [o["type"] for o in short_open]
        print(f"  Open orders (SHORT side): {types_found}")

        sl_orders = [o for o in short_open if o["type"] == "STOP_MARKET"]
        tp_orders = [o for o in short_open if o["type"] == "TAKE_PROFIT_MARKET"]

        if sl_orders:
            sl_price = float(sl_orders[0]["stopPrice"])
            _ok("STOP_MARKET (SL) present", f"stopPrice={sl_price:.4f}")
            if sl_price > entry_price:
                _ok("SL above entry (correct for short)")
            else:
                _fail_check("SL NOT above entry", f"sl={sl_price:.4f}  entry={entry_price:.4f}")
        else:
            _fail_check("STOP_MARKET (SL) missing from open orders")

        if tp_orders:
            tp_price = float(tp_orders[0]["stopPrice"])
            _ok("TAKE_PROFIT_MARKET (TP) present", f"stopPrice={tp_price:.4f}")
            if tp_price < entry_price:
                _ok("TP below entry (correct for short)")
            else:
                _fail_check("TP NOT below entry", f"tp={tp_price:.4f}  entry={entry_price:.4f}")
        else:
            _fail_check("TAKE_PROFIT_MARKET (TP) missing from open orders")

        # ── 6. Cleanup ────────────────────────────────────────────────────────
        section("6 — Cleanup")
        try:
            client.delete("/fapi/v1/allOpenOrders", symbol=_SYMBOL)
            _ok("All open orders cancelled")
        except Exception as exc:
            _fail_check("Cancel open orders", str(exc))

        time.sleep(0.5)

        close_short = Short.exit(client, _SYMBOL)
        print(f"  Binance exit: {close_short}")
        if close_short.get("orderId"):
            _ok("Short exit placed", f"orderId={close_short['orderId']}")
        else:
            _fail_check("Short exit — missing orderId", str(close_short))

        time.sleep(1.0)

        positions3 = client.get("/fapi/v2/positionRisk")
        remaining = [p for p in positions3 if p["symbol"] == _SYMBOL and abs(float(p["positionAmt"])) > 0]
        if not remaining:
            _ok("All positions flat — clean")
        else:
            _fail_check("Positions still open", str([f"{p['positionSide']}={p['positionAmt']}" for p in remaining]))

    except Exception as exc:
        import traceback
        print(f"\nFATAL: {exc}")
        traceback.print_exc()
        _fail_check("Uncaught exception", str(exc))
    finally:
        client.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    section("SUMMARY")
    total = _pass + _fail
    print(f"  {_pass}/{total} checks passed")
    if _fail == 0:
        print("  ALL PASS — Long and Short place and confirm correctly on Binance testnet")
    else:
        print(f"  {_fail} FAILURES — review output above")
    print()


if __name__ == "__main__":
    main()
