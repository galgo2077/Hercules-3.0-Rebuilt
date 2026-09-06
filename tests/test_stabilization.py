from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path

import polars as pl
import pytest


@pytest.mark.parametrize(
    ("stream", "expected"),
    [
        ("btcusdt@kline_1h", "BTCUSDT"),
        ("ethusdt@kline_1h", None),
        ("btcusdt@garbage", None),
        ("btcusdt@kline_99h", None),
        ("btcusdt@kline_1h@extra", None),
        (None, None),
    ],
)
def test_stream_symbol_parsing_is_exact(stream, expected) -> None:
    from Live.Execution import stream_asset

    assert stream_asset(stream, ["BTCUSDT"]) == expected


def test_frame_is_self_contained_and_deterministic() -> None:
    from Dataframe.Frame import FRAME_COLUMNS, build

    start = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    frame = pl.DataFrame(
        {
            "timestamp": [start + dt.timedelta(hours=index) for index in range(40)],
            "open": [100.0 + index for index in range(40)],
            "high": [101.0 + index for index in range(40)],
            "low": [99.0 + index for index in range(40)],
            "close": [100.5 + index for index in range(40)],
            "volume": [1000.0] * 40,
            "asset": ["BTCUSDT"] * 40,
        }
    )
    first = build(frame)
    second = build(frame)
    assert first.columns == list(FRAME_COLUMNS)
    assert first.equals(second)
    assert first["final_signal"][-1] == 1


def test_strategy_evaluate_empty_frame_is_empty() -> None:
    from Strategy.Strategy import evaluate

    result = evaluate(pl.DataFrame(schema={"timestamp": pl.Datetime("ms", "UTC"), "asset": pl.String}))
    assert result.is_empty()
    assert {"action", "side", "target_exposure", "exposure_delta", "entry_allowed", "exit_required", "reason"} <= set(result.columns)


def test_tuner_changes_parameters_used_by_frame() -> None:
    import random
    import tomllib

    from Backtest.Tuner import _candidate

    root = Path(__file__).resolve().parents[1]
    with (root / "SharedData" / "Strategy.toml").open("rb") as handle:
        strategy = tomllib.load(handle)
    with (root / "Backtest" / "AutoTune.toml").open("rb") as handle:
        ranges = tomllib.load(handle)["ranges"]
    candidate = _candidate(strategy, ranges, random.Random(42))  # noqa: S311 - deterministic tuner test
    assert any(candidate["assets"][asset]["rdma_fast_half_life"] != strategy["assets"][asset]["rdma_fast_half_life"] for asset in strategy["assets"])


def test_backtest_reverses_close_before_open_deterministically() -> None:
    from Backtest.Runner import _simulate

    start = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    strategy = pl.DataFrame(
        {
            "timestamp": [start + dt.timedelta(hours=index) for index in range(3)],
            "asset": ["BTCUSDT"] * 3,
            "open": [100.0, 110.0, 100.0],
            "high": [101.0, 111.0, 101.0],
            "low": [99.0, 109.0, 99.0],
            "close": [100.0, 110.0, 100.0],
            "action": ["Entry", "Entry", "Hold"],
            "side": ["Long", "Short", "Short"],
        }
    )
    portfolio = {"allocation": {"BTCUSDT": 1.0}, "trade_size_pct": 0.1, "leverage": 2.0, "stop_loss_pct": 0.5, "take_profit_pct": 0.5}
    backtest = {"execution": {"fee_rate": 0.0, "slippage_rate": 0.0}}
    config = {"assets": {}}
    first = _simulate(strategy, 1000.0, portfolio, backtest, config)
    second = _simulate(strategy, 1000.0, portfolio, backtest, config)
    assert first.trades.equals(second.trades)
    assert first.trades["side"].to_list() == ["long", "short"]
    assert first.trades["exit_reason"].to_list() == ["reversal", "end_of_test"]
    assert abs(float(first.trades["pnl"].sum()) - 38.54545454545455) <= 1e-8


class _PositionClient:
    def get(self, path: str):
        assert path == "/fapi/v2/positionRisk"
        return [
            {"symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "0.1", "markPrice": "100", "entryPrice": "90", "unRealizedProfit": "1"},
            {"symbol": "BTCUSDT", "positionSide": "SHORT", "positionAmt": "-0.2", "markPrice": "100", "entryPrice": "110", "unRealizedProfit": "2"},
        ]


def test_hedge_positions_do_not_overwrite() -> None:
    from Live.Positions import PositionTracker

    tracker = PositionTracker()
    tracker.fetch(_PositionClient())
    assert tracker.get("BTCUSDT", "LONG").size_usdt == 10.0
    assert tracker.get("BTCUSDT", "SHORT").size_usdt == 20.0
    with pytest.raises(RuntimeError, match="both LONG and SHORT"):
        tracker.get("BTCUSDT")


def test_reconcile_discovers_exchange_only_position_after_restart() -> None:
    from Live.Positions import PositionTracker
    from Live.Reconcile import reconcile

    mismatches = reconcile(PositionTracker(), _PositionClient())
    assert {(mismatch.asset, mismatch.position_side, mismatch.local_side, mismatch.exchange_side) for mismatch in mismatches} == {
        ("BTCUSDT", "LONG", "FLAT", "LONG"),
        ("BTCUSDT", "SHORT", "FLAT", "SHORT"),
    }


def test_demo_reversal_closes_and_confirms_before_opening() -> None:
    from Live.Demo import DemoEngine
    from tests.test_orders_e2e import FakeClient

    client = FakeClient()
    client.positions[("BTCUSDT", "SHORT")] = 0.1
    engine = DemoEngine(api_key="key", api_secret="secret")
    engine._execute(client, {"asset": "BTCUSDT", "action": "Entry", "side": "Long"})
    markets = [post for post in client.posts() if post.get("type") == "MARKET"]
    assert [(post["positionSide"], post["side"]) for post in markets] == [("SHORT", "BUY"), ("LONG", "BUY")]
    assert client.positions[("BTCUSDT", "SHORT")] == 0
    assert client.positions[("BTCUSDT", "LONG")] > 0


def test_worker_modes_are_explicit() -> None:
    from Live.Demo import DemoEngine
    from Live.Paper import PaperEngine
    from Live.Real import RealEngine
    from Live.Worker import _engine_for

    assert _engine_for("paper") is PaperEngine
    assert _engine_for("testnet") is DemoEngine
    assert _engine_for("real") is RealEngine
    with pytest.raises(ValueError, match="unsupported"):
        _engine_for("live")


def test_all_modes_start_and_stop_without_trading(monkeypatch) -> None:
    from Live.Demo import DemoEngine
    from Live.Paper import PaperEngine
    from Live.Real import RealEngine

    engines = [
        PaperEngine(),
        DemoEngine(api_key="key", api_secret="secret"),
        RealEngine(api_key="key", api_secret="secret"),
    ]
    for engine in engines:
        monkeypatch.setattr(engine, "_warmup", lambda: None)

        async def stop_listener(current=engine):
            current._running = False

        monkeypatch.setattr(engine, "_listen", stop_listener)
        engine.start()
        assert engine._running is False


def test_lease_acquisition_uses_one_rpc(monkeypatch) -> None:
    from Live.Worker import acquire_lease

    calls = []

    class Response:
        data = True

    class Query:
        def execute(self):
            return Response()

    class Database:
        def rpc(self, name, params):
            calls.append((name, params))
            return Query()

    monkeypatch.setattr("Live.Worker.get_service_client", Database)
    assert acquire_lease("account", "worker", 30) is True
    assert calls == [("acquire_worker_lease", {"p_account_id": "account", "p_worker_id": "worker", "p_ttl_seconds": 30})]


def test_real_listener_initializes_hedge_mode(monkeypatch) -> None:
    from Live.Real import RealEngine

    class Client:
        hedge = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def ensure_hedge_mode(self):
            self.hedge = True

        def get(self, path, **kwargs):
            if path == "/fapi/v2/account":
                return {"totalWalletBalance": "1000"}
            if path == "/fapi/v2/positionRisk":
                return []
            raise AssertionError(path)

    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    client = Client()
    engine = RealEngine(api_key="key", api_secret="secret")
    monkeypatch.setattr(engine, "_client", lambda: client)
    monkeypatch.setattr("Live.Demo.websockets.connect", lambda url: Socket())
    asyncio.run(engine._listen())
    assert client.hedge is True


def test_schema_has_atomic_lease_rls_and_rerunnable_policies() -> None:
    schema = (Path(__file__).resolve().parents[1] / "Storage" / "schema.sql").read_text(encoding="utf-8")
    assert "PRIMARY KEY (account_id, asset, side)" in schema
    assert "CREATE OR REPLACE FUNCTION acquire_worker_lease" in schema
    assert "ALTER TABLE worker_leases ENABLE ROW LEVEL SECURITY" in schema
    assert schema.count("DROP POLICY IF EXISTS") == schema.count("CREATE POLICY")
