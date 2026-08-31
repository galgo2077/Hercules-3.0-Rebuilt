"""Verify order modules place correct Binance API calls — no network, FakeClient only."""

from __future__ import annotations

import pytest


class FakeClient:
    def __init__(self, price: float = 50_000.0, position_rows: list[dict] | None = None) -> None:
        self.price = price
        self.position_rows = position_rows or []
        self.calls: list[tuple] = []

    def set_leverage(self, symbol: str, leverage: int) -> None:
        self.calls.append(("set_leverage", symbol, leverage))

    def get(self, path: str, **kwargs) -> dict:
        self.calls.append(("GET", path, kwargs))
        if "ticker/price" in path:
            return {"price": str(self.price)}
        if "positionRisk" in path:
            return self.position_rows
        return {}

    def post(self, path: str, **kwargs) -> dict:
        self.calls.append(("POST", path, kwargs))
        return {"orderId": len(self.calls)}

    def posts(self) -> list[dict]:
        return [kw for method, path, kw in self.calls if method == "POST"]

    def post_types(self) -> list[str]:
        return [kw.get("type", "") for kw in self.posts()]


# ── Long entry ────────────────────────────────────────────────────────────────

def test_long_enter_sets_leverage():
    from Live.Orders import Long
    c = FakeClient()
    Long.enter(c, "BTCUSDT", 1000.0, 8)
    assert ("set_leverage", "BTCUSDT", 8) in c.calls


def test_long_enter_places_one_market_order():
    from Live.Orders import Long
    c = FakeClient()
    Long.enter(c, "BTCUSDT", 1000.0, 8)
    assert c.post_types().count("MARKET") == 1


def test_long_enter_no_stop_orders():
    from Live.Orders import Long
    c = FakeClient()
    Long.enter(c, "BTCUSDT", 1000.0, 8)
    types = c.post_types()
    assert "STOP_MARKET" not in types
    assert "TAKE_PROFIT_MARKET" not in types


def test_long_enter_qty_calculation():
    from Live.Orders import Long
    price = 50_000.0
    usdt = 7_200.0
    lev = 8
    expected_qty = round(usdt / price, 3)  # usdt_amount is leveraged notional
    c = FakeClient(price=price)
    Long.enter(c, "BTCUSDT", usdt, lev)
    market_post = next(kw for kw in c.posts() if kw.get("type") == "MARKET")
    assert market_post["quantity"] == expected_qty


def test_long_enter_positionside_long():
    from Live.Orders import Long
    c = FakeClient()
    Long.enter(c, "BTCUSDT", 1000.0, 8)
    market_post = next(kw for kw in c.posts() if kw.get("type") == "MARKET")
    assert market_post["positionSide"] == "LONG"


def test_long_enter_side_buy():
    from Live.Orders import Long
    c = FakeClient()
    Long.enter(c, "BTCUSDT", 1000.0, 8)
    market_post = next(kw for kw in c.posts() if kw.get("type") == "MARKET")
    assert market_post["side"] == "BUY"


# ── Long exit ─────────────────────────────────────────────────────────────────

def test_long_exit_places_close():
    from Live.Orders import Long
    c = FakeClient(position_rows=[{"symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "0.0123456789"}])
    Long.exit(c, "BTCUSDT")
    p = c.posts()[0]
    assert p["side"] == "SELL"
    assert p["positionSide"] == "LONG"
    assert p["quantity"] == 0.01234568


def test_long_exit_uses_explicit_quantity():
    from Live.Orders import Long
    c = FakeClient()
    Long.exit(c, "BTCUSDT", quantity=0.0123456789)
    assert c.posts()[0]["quantity"] == 0.01234568


def test_long_exit_without_position_rejects_without_post():
    from Live.Orders import Long
    c = FakeClient()
    with pytest.raises(ValueError, match="no long position"):
        Long.exit(c, "BTCUSDT")
    assert c.posts() == []


# ── Short entry — with SL+TP ─────────────────────────────────────────────────

def test_short_enter_with_sl_tp_places_three_orders():
    from Live.Orders import Short
    c = FakeClient(price=50_000.0)
    Short.enter(c, "BTCUSDT", 7_200.0, 8, stop_loss_pct=0.06, take_profit_pct=0.03)
    types = c.post_types()
    assert types.count("MARKET") == 1
    assert types.count("STOP_MARKET") == 1
    assert types.count("TAKE_PROFIT_MARKET") == 1


def test_short_enter_sl_price_correct():
    from Live.Orders import Short
    price = 50_000.0
    c = FakeClient(price=price)
    Short.enter(c, "BTCUSDT", 1000.0, 8, stop_loss_pct=0.06, take_profit_pct=0.03)
    sl_post = next(kw for kw in c.posts() if kw.get("type") == "STOP_MARKET")
    assert sl_post["stopPrice"] == round(price * 1.06, 2)  # 53000.0


def test_short_enter_tp_price_correct():
    from Live.Orders import Short
    price = 50_000.0
    c = FakeClient(price=price)
    Short.enter(c, "BTCUSDT", 1000.0, 8, stop_loss_pct=0.06, take_profit_pct=0.03)
    tp_post = next(kw for kw in c.posts() if kw.get("type") == "TAKE_PROFIT_MARKET")
    assert tp_post["stopPrice"] == round(price * 0.97, 2)  # 48500.0


def test_short_enter_sl_above_entry():
    from Live.Orders import Short
    price = 50_000.0
    c = FakeClient(price=price)
    Short.enter(c, "BTCUSDT", 1000.0, 8, stop_loss_pct=0.06, take_profit_pct=0.03)
    sl_post = next(kw for kw in c.posts() if kw.get("type") == "STOP_MARKET")
    assert sl_post["stopPrice"] > price


def test_short_enter_tp_below_entry():
    from Live.Orders import Short
    price = 50_000.0
    c = FakeClient(price=price)
    Short.enter(c, "BTCUSDT", 1000.0, 8, stop_loss_pct=0.06, take_profit_pct=0.03)
    tp_post = next(kw for kw in c.posts() if kw.get("type") == "TAKE_PROFIT_MARKET")
    assert tp_post["stopPrice"] < price


def test_short_enter_without_sl_places_two_orders():
    from Live.Orders import Short
    c = FakeClient()
    Short.enter(c, "BTCUSDT", 1000.0, 8, stop_loss_pct=None, take_profit_pct=0.03)
    types = c.post_types()
    assert "STOP_MARKET" not in types
    assert types.count("TAKE_PROFIT_MARKET") == 1


def test_short_enter_without_tp_places_two_orders():
    from Live.Orders import Short
    c = FakeClient()
    Short.enter(c, "BTCUSDT", 1000.0, 8, stop_loss_pct=0.06, take_profit_pct=None)
    types = c.post_types()
    assert "TAKE_PROFIT_MARKET" not in types
    assert types.count("STOP_MARKET") == 1


def test_short_enter_no_sl_no_tp_one_order():
    from Live.Orders import Short
    c = FakeClient()
    Short.enter(c, "BTCUSDT", 1000.0, 8)
    assert len(c.posts()) == 1
    assert c.post_types()[0] == "MARKET"


def test_short_entry_positionside_short():
    from Live.Orders import Short
    c = FakeClient()
    Short.enter(c, "BTCUSDT", 1000.0, 8, stop_loss_pct=0.06, take_profit_pct=0.03)
    for p in c.posts():
        assert p.get("positionSide") == "SHORT"


def test_short_entry_market_side_sell():
    from Live.Orders import Short
    c = FakeClient()
    Short.enter(c, "BTCUSDT", 1000.0, 8)
    market_post = next(kw for kw in c.posts() if kw.get("type") == "MARKET")
    assert market_post["side"] == "SELL"


def test_short_sl_order_side_buy():
    from Live.Orders import Short
    c = FakeClient()
    Short.enter(c, "BTCUSDT", 1000.0, 8, stop_loss_pct=0.06)
    sl_post = next(kw for kw in c.posts() if kw.get("type") == "STOP_MARKET")
    assert sl_post["side"] == "BUY"


def test_short_tp_order_side_buy():
    from Live.Orders import Short
    c = FakeClient()
    Short.enter(c, "BTCUSDT", 1000.0, 8, take_profit_pct=0.03)
    tp_post = next(kw for kw in c.posts() if kw.get("type") == "TAKE_PROFIT_MARKET")
    assert tp_post["side"] == "BUY"


def test_short_enter_ethusdt_no_sl_only_tp():
    from Live.Orders import Short
    c = FakeClient(price=3_000.0)
    Short.enter(c, "ETHUSDT", 500.0, 15, stop_loss_pct=None, take_profit_pct=0.025)
    types = c.post_types()
    assert "STOP_MARKET" not in types
    assert types.count("TAKE_PROFIT_MARKET") == 1


def test_short_enter_sets_leverage():
    from Live.Orders import Short
    c = FakeClient()
    Short.enter(c, "BTCUSDT", 1000.0, 8, stop_loss_pct=0.06, take_profit_pct=0.03)
    assert ("set_leverage", "BTCUSDT", 8) in c.calls


# ── Short exit ────────────────────────────────────────────────────────────────

def test_short_exit_places_close():
    from Live.Orders import Short
    c = FakeClient(position_rows=[{"symbol": "BTCUSDT", "positionSide": "SHORT", "positionAmt": "0.0123456789"}])
    Short.exit(c, "BTCUSDT")
    p = c.posts()[0]
    assert p["side"] == "BUY"
    assert p["positionSide"] == "SHORT"
    assert p["quantity"] == 0.01234568


def test_short_exit_uses_explicit_quantity():
    from Live.Orders import Short
    c = FakeClient()
    Short.exit(c, "BTCUSDT", quantity=0.0123456789)
    assert c.posts()[0]["quantity"] == 0.01234568


def test_short_exit_without_position_rejects_without_post():
    from Live.Orders import Short
    c = FakeClient()
    with pytest.raises(ValueError, match="no short position"):
        Short.exit(c, "BTCUSDT")
    assert c.posts() == []
