"""CandleBuffer: ingest, dedup, ready gate, health, WS parse, reset."""

from Dataframe.CandleBuffer import CandleBuffer


def _candle(i: int, asset: str = "BTCUSDT") -> dict:
    return {"t": i * 3_600_000, "o": 1.0, "h": 1.1, "l": 0.9, "c": 1.05, "v": 100.0}


def _fill(buf: CandleBuffer, n: int, asset: str = "BTCUSDT") -> None:
    for i in range(n):
        buf.ingest(asset, _candle(i, asset), is_closed=True)


def test_not_ready_below_min():
    buf = CandleBuffer()
    _fill(buf, 100)
    assert not buf.ready("BTCUSDT", 200)


def test_ready_at_min():
    buf = CandleBuffer()
    _fill(buf, 200)
    assert buf.ready("BTCUSDT", 200)


def test_capacity_evicts_oldest():
    buf = CandleBuffer(capacity=50)
    _fill(buf, 100)
    assert len(buf.get("BTCUSDT")) == 50


def test_dedup_same_timestamp():
    buf = CandleBuffer()
    buf.ingest("BTCUSDT", _candle(0), is_closed=True)
    buf.ingest("BTCUSDT", _candle(0), is_closed=True)
    assert len(buf.get("BTCUSDT")) == 1


def test_open_candle_not_stored():
    buf = CandleBuffer()
    stored = buf.ingest("BTCUSDT", _candle(0), is_closed=False)
    assert not stored
    assert len(buf.get("BTCUSDT")) == 0


def test_health_keys():
    buf = CandleBuffer()
    _fill(buf, 5)
    h = buf.health("BTCUSDT")
    assert {"asset", "bars", "latest_ts", "ready"} == set(h.keys())
    assert h["bars"] == 5


def test_to_dicts_schema():
    buf = CandleBuffer()
    _fill(buf, 3)
    rows = buf.to_dicts("BTCUSDT")
    assert len(rows) == 3
    assert set(rows[0].keys()) == {"timestamp", "open", "high", "low", "close", "volume", "asset"}


def test_ingest_ws_closed():
    buf = CandleBuffer()
    msg = {"stream": "btcusdt@kline_1h", "data": {"k": {**_candle(0), "x": True}}}
    assert buf.ingest_ws("BTCUSDT", msg)
    assert len(buf.get("BTCUSDT")) == 1


def test_ingest_ws_not_closed():
    buf = CandleBuffer()
    msg = {"stream": "btcusdt@kline_1h", "data": {"k": {**_candle(0), "x": False}}}
    assert not buf.ingest_ws("BTCUSDT", msg)


def test_reset_single_asset():
    buf = CandleBuffer()
    _fill(buf, 10, "BTCUSDT")
    _fill(buf, 10, "ETHUSDT")
    buf.reset("BTCUSDT")
    assert len(buf.get("BTCUSDT")) == 0
    assert len(buf.get("ETHUSDT")) == 10


def test_reset_all():
    buf = CandleBuffer()
    _fill(buf, 5, "BTCUSDT")
    _fill(buf, 5, "ETHUSDT")
    buf.reset()
    assert buf.get("BTCUSDT") == []
    assert buf.get("ETHUSDT") == []


def test_multi_asset_independent():
    buf = CandleBuffer()
    _fill(buf, 200, "BTCUSDT")
    _fill(buf, 50, "ETHUSDT")
    assert buf.ready("BTCUSDT", 200)
    assert not buf.ready("ETHUSDT", 200)
