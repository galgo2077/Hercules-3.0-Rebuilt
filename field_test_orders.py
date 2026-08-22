#!/usr/bin/env python3
"""Field test — places real Long + Short (with SL/TP) on Binance TESTNET.

Run:
    source .venv/bin/activate
    python field_test_orders.py

Needs BINANCE_API_KEY and BINANCE_API_SECRET pointing to a TESTNET account.
Get testnet keys: https://testnet.binancefuture.com
WARNING: places real orders on testnet. Cleans up after itself (cancels + closes).
"""

from __future__ import annotations

import os
import sys
import time

_TESTNET = "https://testnet.binancefuture.com"
_SYMBOL = "BTCUSDT"
_LEVERAGE = 1  # leverage=1 keeps notional minimal
_SL_PCT = 0.03  # tight for testnet verification
_TP_PCT = 0.02

_pass = 0
_fail = 0


def _ok(label: str, detail: str = "") -> None:
    global _pass
    _pass += 1
    print(f"  [PASS] {label}" + (f"  ({detail})" if detail else ""))


def _fail_check(label: str, detail: str = "") -> None:
    global _fail
    _fail += 1
    print(f"  [FAIL] {label}" + (f"  ({detail})" if detail else ""))


def section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


def main() -> None:
    if not os.environ.get("BINANCE_API_KEY") or not os.environ.get("BINANCE_API_SECRET"):
        print("ERROR: set BINANCE_API_KEY and BINANCE_API_SECRET (testnet keys)")
        sys.exit(1)

    from Live._client import BinanceClient
    from Live.Orders import Long, Short

    client = BinanceClient(_TESTNET)
    entry_price: float = 0.0

    try:
        # ── 1. Hedge mode ─────────────────────────────────────────────────────
        section("1 — Hedge mode")
        client.ensure_hedge_mode()
        resp = client.get("/fapi/v1/positionSide/dual")
        dual = resp.get("dualSidePosition", False)
        if dual:
            _ok("dualSidePosition=true confirmed")
        else:
            _fail_check("dualSidePosition still false after ensure_hedge_mode", str(resp))
            print("  Cannot continue without hedge mode — aborting")
            return

        # ── 2. Price + tick size ──────────────────────────────────────────────
        section("2 — Market data")
        price_resp = client.get("/fapi/v1/ticker/price", symbol=_SYMBOL)
        entry_price = float(price_resp["price"])
        tick = client.tick_size(_SYMBOL)
        qty = round(_LEVERAGE * 5.5 / entry_price, 3)  # ~$5.5 notional (testnet min ~$5)
        if qty < 0.001:
            qty = 0.001
        print(f"  {_SYMBOL} price : {entry_price:.2f}")
        print(f"  tickSize       : {tick}")
        print(f"  order qty      : {qty} (notional ~${qty * entry_price:.1f})")
        _ok("price fetched", f"{entry_price:.2f}")
        _ok("tickSize fetched", str(tick))

        # ── 3. Long entry ─────────────────────────────────────────────────────
        section("3 — Long entry (no SL, no TP)")
        client.set_leverage(_SYMBOL, _LEVERAGE)
        long_resp = Long.enter(client, _SYMBOL, qty * entry_price, _LEVERAGE)
        print(f"  Binance response: {long_resp}")
        long_order_id = long_resp.get("orderId")
        if long_order_id:
            _ok("Long MARKET order placed", f"orderId={long_order_id}")
        else:
            _fail_check("Long order missing orderId", str(long_resp))

        time.sleep(0.8)

        # Verify long position exists in account
        positions = client.get("/fapi/v2/positionRisk")
        long_pos = next((p for p in positions if p["symbol"] == _SYMBOL and p["positionSide"] == "LONG"), None)
        long_amt = float(long_pos["positionAmt"]) if long_pos else 0.0
        if long_amt > 0:
            _ok("Long position confirmed on exchange", f"positionAmt={long_amt}")
        else:
            _fail_check("Long position not visible", f"positionAmt={long_amt}")

        # Verify NO open stop/tp orders for LONG side
        open_orders = client.get("/fapi/v1/openOrders", symbol=_SYMBOL)
        long_stops = [o for o in open_orders if o.get("positionSide") == "LONG" and o["type"] in ("STOP_MARKET", "TAKE_PROFIT_MARKET")]
        if not long_stops:
            _ok("Long has NO SL/TP orders (correct)")
        else:
            _fail_check("Long unexpectedly has SL/TP orders", str([o["type"] for o in long_stops]))

        # ── 4. Close Long ─────────────────────────────────────────────────────
        section("4 — Close Long")
        close_resp = Long.exit(client, _SYMBOL)
        print(f"  Binance response: {close_resp}")
        if close_resp.get("orderId"):
            _ok("Long exit placed", f"orderId={close_resp['orderId']}")
        else:
            _fail_check("Long exit missing orderId", str(close_resp))
        time.sleep(0.8)

        # ── 5. Short entry with SL + TP ───────────────────────────────────────
        section("5 — Short entry (with SL + TP)")
        short_resp = Short.enter(
            client, _SYMBOL, qty * entry_price, _LEVERAGE,
            stop_loss_pct=_SL_PCT,
            take_profit_pct=_TP_PCT,
        )
        print(f"  Binance response: {short_resp}")
        short_order_id = short_resp.get("orderId")
        if short_order_id:
            _ok("Short MARKET order placed", f"orderId={short_order_id}")
        else:
            _fail_check("Short order missing orderId", str(short_resp))

        time.sleep(0.8)

        # Verify short position in account
        positions2 = client.get("/fapi/v2/positionRisk")
        short_pos = next((p for p in positions2 if p["symbol"] == _SYMBOL and p["positionSide"] == "SHORT"), None)
        short_amt = abs(float(short_pos["positionAmt"])) if short_pos else 0.0
        if short_amt > 0:
            _ok("Short position confirmed on exchange", f"positionAmt={-short_amt}")
        else:
            _fail_check("Short position not visible", f"positionAmt={short_amt}")

        # Verify SL + TP orders exist
        open_orders2 = client.get("/fapi/v1/openOrders", symbol=_SYMBOL)
        short_open = [o for o in open_orders2 if o.get("positionSide") == "SHORT"]
        order_types = [o["type"] for o in short_open]
        print(f"  Open orders on SHORT side: {order_types}")

        sl_orders = [o for o in short_open if o["type"] == "STOP_MARKET"]
        tp_orders = [o for o in short_open if o["type"] == "TAKE_PROFIT_MARKET"]

        if sl_orders:
            sl_price = float(sl_orders[0]["stopPrice"])
            _ok("STOP_MARKET (SL) order present", f"stopPrice={sl_price:.2f} (entry={entry_price:.2f} +{_SL_PCT*100:.0f}%)")
            if sl_price > entry_price:
                _ok("SL price is above entry (correct for short)")
            else:
                _fail_check("SL price is NOT above entry", f"sl={sl_price} entry={entry_price}")
        else:
            _fail_check("STOP_MARKET (SL) order missing")

        if tp_orders:
            tp_price = float(tp_orders[0]["stopPrice"])
            _ok("TAKE_PROFIT_MARKET (TP) order present", f"stopPrice={tp_price:.2f} (entry={entry_price:.2f} -{_TP_PCT*100:.0f}%)")
            if tp_price < entry_price:
                _ok("TP price is below entry (correct for short)")
            else:
                _fail_check("TP price is NOT below entry", f"tp={tp_price} entry={entry_price}")
        else:
            _fail_check("TAKE_PROFIT_MARKET (TP) order missing")

        # ── 6. Cleanup ────────────────────────────────────────────────────────
        section("6 — Cleanup")
        try:
            client.delete("/fapi/v1/allOpenOrders", symbol=_SYMBOL)
            _ok("All open orders cancelled")
        except Exception as exc:
            _fail_check("Cancel open orders", str(exc))

        time.sleep(0.3)
        close_short = Short.exit(client, _SYMBOL)
        if close_short.get("orderId"):
            _ok("Short exit placed", f"orderId={close_short['orderId']}")
        else:
            _fail_check("Short exit", str(close_short))

        time.sleep(0.8)
        positions3 = client.get("/fapi/v2/positionRisk")
        remaining = [p for p in positions3 if p["symbol"] == _SYMBOL and abs(float(p["positionAmt"])) > 0]
        if not remaining:
            _ok("All positions flat — clean")
        else:
            _fail_check("Positions remain open", str([f"{p['positionSide']}={p['positionAmt']}" for p in remaining]))

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
        print("  ALL PASS — Long and Short orders execute correctly on Binance testnet")
    else:
        print(f"  {_fail} FAILURES — see above")
    print()


if __name__ == "__main__":
    main()
