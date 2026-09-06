"""Behavioral order tests with a stateful exchange fake."""

from __future__ import annotations

import pytest


class FakeClient:
    def __init__(
        self,
        price: float = 50_000.0,
        fill_ratio: float = 1.0,
        reject_type: str | None = None,
        entry_price: float | None = None,
        hide_positions: bool = False,
        hide_open_orders: bool = False,
        reject_cancel: bool = False,
    ) -> None:
        self.price = price
        self.entry_price = price if entry_price is None else entry_price
        self.fill_ratio = fill_ratio
        self.reject_type = reject_type
        self.hide_positions = hide_positions
        self.hide_open_orders = hide_open_orders
        self.reject_cancel = reject_cancel
        self.calls: list[tuple] = []
        self.positions: dict[tuple[str, str], float] = {}
        self.open_orders: list[dict] = []

    def set_leverage(self, symbol: str, leverage: int) -> None:
        self.calls.append(("set_leverage", symbol, leverage))

    def quantity_filters(self, symbol: str) -> dict[str, float]:
        return {"step_size": 0.001, "min_qty": 0.001, "min_notional": 5.0}

    def round_price(self, symbol: str, price: float, direction: str = "nearest") -> float:
        self.calls.append(("round_price", symbol, direction))
        return round(price, 2)

    def get(self, path: str, **kwargs):
        self.calls.append(("GET", path, kwargs))
        if "ticker/price" in path:
            return {"price": str(self.price)}
        if "positionRisk" in path:
            if self.hide_positions:
                return []
            return [
                {
                    "symbol": symbol,
                    "positionSide": side,
                    "positionAmt": str(quantity if side == "LONG" else -quantity),
                    "entryPrice": str(self.entry_price),
                    "markPrice": str(self.price),
                    "unRealizedProfit": "0",
                }
                for (symbol, side), quantity in self.positions.items()
                if quantity > 0
            ]
        if "openOrders" in path:
            return [] if self.hide_open_orders else list(self.open_orders)
        if path == "/fapi/v2/account":
            return {"totalWalletBalance": "10000", "totalMarginBalance": "10000", "availableBalance": "10000"}
        return {}

    def post(self, path: str, **kwargs):
        self.calls.append(("POST", path, kwargs))
        if kwargs.get("type") == self.reject_type:
            raise RuntimeError("rejected")
        if kwargs.get("type") == "MARKET":
            key = (kwargs["symbol"], kwargs["positionSide"])
            opens = (kwargs["positionSide"], kwargs["side"]) in {("LONG", "BUY"), ("SHORT", "SELL")}
            self.positions[key] = float(kwargs["quantity"]) * self.fill_ratio if opens else 0.0
        result = {"orderId": len(self.calls)}
        if kwargs.get("type") in {"STOP_MARKET", "TAKE_PROFIT_MARKET"}:
            self.open_orders.append({**kwargs, **result})
        return result

    def delete(self, path: str, **kwargs):
        self.calls.append(("DELETE", path, kwargs))
        if self.reject_cancel:
            raise RuntimeError("cancel rejected")
        self.open_orders = [order for order in self.open_orders if order.get("orderId") != kwargs.get("orderId")]
        return {"code": 200}

    def posts(self) -> list[dict]:
        return [kwargs for method, _, kwargs in self.calls if method == "POST"]


def _types(client: FakeClient) -> list[str]:
    return [post.get("type", "") for post in client.posts()]


@pytest.mark.parametrize(
    ("module", "side", "open_side", "close_side"),
    [("Long", "LONG", "BUY", "SELL"), ("Short", "SHORT", "SELL", "BUY")],
)
def test_entry_is_sized_once_and_protected(module: str, side: str, open_side: str, close_side: str) -> None:
    from Live.Orders import Long, Short

    orders = Long if module == "Long" else Short
    client = FakeClient()
    orders.enter(client, "BTCUSDT", 7_200.0, 8, stop_loss_pct=0.06, take_profit_pct=0.03)
    market = next(post for post in client.posts() if post["type"] == "MARKET")
    assert market["quantity"] == 0.144
    assert market["positionSide"] == side
    assert market["side"] == open_side
    assert _types(client).count("STOP_MARKET") == 1
    assert _types(client).count("TAKE_PROFIT_MARKET") == 1
    assert all(post["side"] == close_side for post in client.posts() if post["type"] != "MARKET")
    assert all(post.get("closePosition") == "true" and "quantity" not in post for post in client.posts() if post["type"] != "MARKET")
    assert client.calls.count(("set_leverage", "BTCUSDT", 8)) == 1


def test_partial_fill_uses_exchange_close_position_protection() -> None:
    from Live.Orders import Long

    client = FakeClient(fill_ratio=0.5)
    Long.enter(client, "BTCUSDT", 1_000.0, 2, take_profit_pct=0.03)
    protection = next(post for post in client.posts() if post["type"] == "TAKE_PROFIT_MARKET")
    assert protection["closePosition"] == "true"
    assert "quantity" not in protection


@pytest.mark.parametrize(("module", "side"), [("Long", "LONG"), ("Short", "SHORT")])
def test_protection_failure_emergency_closes(module: str, side: str) -> None:
    from Live.Orders import Long, Short

    orders = Long if module == "Long" else Short
    client = FakeClient(reject_type="STOP_MARKET")
    with pytest.raises(RuntimeError, match="protection failed"):
        orders.enter(client, "BTCUSDT", 1_000.0, 2, stop_loss_pct=0.06)
    assert client.positions[("BTCUSDT", side)] == 0


@pytest.mark.parametrize(("module", "side", "close_side"), [("Long", "LONG", "SELL"), ("Short", "SHORT", "BUY")])
def test_exit_uses_exchange_position_quantity(module: str, side: str, close_side: str) -> None:
    from Live.Orders import Long, Short

    orders = Long if module == "Long" else Short
    client = FakeClient()
    client.positions[("BTCUSDT", side)] = 0.123
    orders.exit(client, "BTCUSDT")
    close = client.posts()[-1]
    assert close == {"symbol": "BTCUSDT", "side": close_side, "type": "MARKET", "positionSide": side, "quantity": 0.123}
    assert client.open_orders == []


def test_exit_cancels_only_matching_hedge_side_protection() -> None:
    from Live.Orders import Long

    client = FakeClient()
    client.positions[("BTCUSDT", "LONG")] = 0.1
    client.positions[("BTCUSDT", "SHORT")] = 0.2
    client.open_orders = [
        {"orderId": 1, "positionSide": "LONG"},
        {"orderId": 2, "positionSide": "SHORT"},
    ]
    Long.exit(client, "BTCUSDT")
    assert client.open_orders == [{"orderId": 2, "positionSide": "SHORT"}]


def test_exit_confirms_close_before_reporting_cancellation_failure() -> None:
    from Live.Orders import Long

    client = FakeClient(reject_cancel=True)
    client.positions[("BTCUSDT", "LONG")] = 0.1
    client.open_orders = [{"orderId": 1, "positionSide": "LONG"}]
    with pytest.raises(RuntimeError, match="closed but protection cancellation failed"):
        Long.exit(client, "BTCUSDT")
    assert client.positions[("BTCUSDT", "LONG")] == 0


@pytest.mark.parametrize("quantity", [0, -1, float("nan"), float("inf")])
def test_invalid_quantities_are_rejected(quantity: float) -> None:
    from Live.Execution import quantize_quantity

    with pytest.raises(ValueError, match="finite and positive"):
        quantize_quantity(quantity, 0.001)


@pytest.mark.parametrize("percentage", [0, -0.1, 1, float("nan")])
def test_invalid_protection_is_rejected_before_entry(percentage: float) -> None:
    from Live.Orders import Long

    client = FakeClient()
    with pytest.raises(ValueError, match="between 0 and 1"):
        Long.enter(client, "BTCUSDT", 1_000, 2, stop_loss_pct=percentage)
    assert client.posts() == []


def test_invalid_exchange_entry_price_emergency_closes() -> None:
    from Live.Orders import Long

    client = FakeClient(entry_price=0)
    with pytest.raises(RuntimeError, match="invalid LONG entry price"):
        Long.enter(client, "BTCUSDT", 1_000, 2, take_profit_pct=0.03)
    assert client.positions[("BTCUSDT", "LONG")] == 0


def test_missing_entry_confirmation_sends_emergency_close() -> None:
    from Live.Orders import Short

    client = FakeClient(hide_positions=True)
    with pytest.raises(RuntimeError, match="emergency close sent"):
        Short.enter(client, "BTCUSDT", 1_000, 2, take_profit_pct=0.03)
    markets = [post for post in client.posts() if post.get("type") == "MARKET"]
    assert [(order["side"], order["positionSide"]) for order in markets] == [("SELL", "SHORT"), ("BUY", "SHORT")]


def test_unconfirmed_protection_emergency_closes() -> None:
    from Live.Orders import Long

    client = FakeClient(hide_open_orders=True)
    with pytest.raises(RuntimeError, match="protection failed"):
        Long.enter(client, "BTCUSDT", 1_000, 2, stop_loss_pct=0.06, take_profit_pct=0.03)
    assert client.positions[("BTCUSDT", "LONG")] == 0


def test_protection_rounds_away_from_entry() -> None:
    from Live.Orders import Long, Short

    long_client = FakeClient()
    Long.enter(long_client, "BTCUSDT", 1_000, 2, stop_loss_pct=0.06, take_profit_pct=0.03)
    assert ("round_price", "BTCUSDT", "down") in long_client.calls
    assert ("round_price", "BTCUSDT", "up") in long_client.calls
    short_client = FakeClient()
    Short.enter(short_client, "BTCUSDT", 1_000, 2, stop_loss_pct=0.06, take_profit_pct=0.03)
    directions = [call[2] for call in short_client.calls if call[0] == "round_price"]
    assert directions == ["up", "down"]


def test_missing_position_cannot_send_zero_quantity() -> None:
    from Live.Orders import Short

    with pytest.raises(RuntimeError, match="missing SHORT"):
        Short.exit(FakeClient(), "BTCUSDT")


def test_step_size_rounds_down_and_enforces_minimum() -> None:
    from Live.Execution import order_quantity, quantize_quantity

    client = FakeClient(price=3.0)
    assert quantize_quantity(1.239, 0.05) == 1.2
    assert order_quantity(client, "BTCUSDT", 5.01, 3.0) == 1.67
    with pytest.raises(ValueError, match="below exchange minimum"):
        order_quantity(client, "BTCUSDT", 4.99, 3.0)


def test_binance_client_routes_protection_to_algo_api(monkeypatch) -> None:
    from Live._client import BinanceClient

    client = BinanceClient("https://example.invalid", api_key="key", api_secret="secret")
    calls = []
    monkeypatch.setattr(client, "post", lambda path, **params: calls.append((path, params)) or {"algoId": 1})
    client.place_protection(symbol="BTCUSDT", type="STOP_MARKET", stopPrice=90, positionSide="LONG", side="SELL", closePosition="true")
    assert calls == [
        (
            "/fapi/v1/algoOrder",
            {
                "symbol": "BTCUSDT",
                "type": "STOP_MARKET",
                "positionSide": "LONG",
                "side": "SELL",
                "closePosition": "true",
                "algoType": "CONDITIONAL",
                "triggerPrice": 90,
            },
        )
    ]
    client.close()


def test_binance_filter_cache_is_per_exchange_client(monkeypatch) -> None:
    from Live._client import BinanceClient

    def exchange_info(step: str) -> dict:
        return {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "filters": [
                        {"filterType": "LOT_SIZE", "stepSize": step, "minQty": step},
                        {"filterType": "MIN_NOTIONAL", "notional": "5"},
                    ],
                }
            ]
        }

    testnet = BinanceClient("https://testnet.invalid", api_key="key", api_secret="secret")
    real = BinanceClient("https://real.invalid", api_key="key", api_secret="secret")
    monkeypatch.setattr(testnet, "_get_public", lambda *_args, **_kwargs: exchange_info("0.001"))
    monkeypatch.setattr(real, "_get_public", lambda *_args, **_kwargs: exchange_info("0.01"))
    assert testnet.quantity_filters("BTCUSDT")["step_size"] == 0.001
    assert real.quantity_filters("BTCUSDT")["step_size"] == 0.01
    testnet.close()
    real.close()
