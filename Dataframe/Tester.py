"""Dataframe module tester — offline, no network calls."""

import math

from Dataframe.Binance import OHLCV_SCHEMA
from Dataframe.CandleBuffer import CandleBuffer
from Dataframe.Compute import backend, rolling_mean, rolling_slope
from Dataframe.Frame import FRAME_COLUMNS, _build_config

passed = 0
total = 0


def check(label: str, ok: bool, value) -> None:
    global passed, total
    total += 1
    if ok:
        passed += 1
        print(f"[PASS] {label}: {value}")
    else:
        print(f"[FAIL] {label}: {value}")


# ── CandleBuffer ─────────────────────────────────────────────────────────────

buf = CandleBuffer(capacity=500)
for i in range(250):
    buf.ingest("BTCUSDT", {"t": i * 60000, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 10.0})

check("CandleBuffer.ready(200)=True", buf.ready("BTCUSDT", 200) is True, buf.ready("BTCUSDT", 200))
check("CandleBuffer bars=250", len(buf.get("BTCUSDT")) == 250, len(buf.get("BTCUSDT")))

h = buf.health("BTCUSDT")
health_keys = {"asset", "bars", "latest_ts", "ready"}
check("CandleBuffer.health() keys", health_keys.issubset(h.keys()), set(h.keys()))

# dedup: reingest last candle's timestamp — must not grow
last_ts = buf.get("BTCUSDT")[-1].timestamp_ms
buf.ingest("BTCUSDT", {"t": last_ts, "o": 9.0, "h": 9.0, "l": 9.0, "c": 9.0, "v": 9.0})
check("CandleBuffer dedup no grow", len(buf.get("BTCUSDT")) == 250, len(buf.get("BTCUSDT")))

dicts = buf.to_dicts("BTCUSDT")
dict_keys = {"timestamp", "open", "high", "low", "close", "volume", "asset"}
check("CandleBuffer.to_dicts schema", dict_keys.issubset(dicts[0].keys()), set(dicts[0].keys()))

# ── Compute ──────────────────────────────────────────────────────────────────

be = backend()
check("Compute.backend()", be in ("cpu", "cuda"), be)

rm = rolling_mean([1, 2, 3, 4, 5], 3)
rm_nan2 = math.isnan(rm[0]) and math.isnan(rm[1])
rm_vals = [round(float(v), 6) for v in rm[2:]]
check("rolling_mean nans at 0,1", rm_nan2, [rm[0], rm[1]])
check("rolling_mean values [2,3,4]", rm_vals == [2.0, 3.0, 4.0], rm_vals)

rs = rolling_slope([1, 2, 3, 4, 5], 3)
rs_nan2 = math.isnan(rs[0]) and math.isnan(rs[1])
rs_vals = [round(float(v), 6) for v in rs[2:]]
check("rolling_slope nans at 0,1", rs_nan2, [rs[0], rs[1]])
check("rolling_slope values [1,1,1]", rs_vals == [1.0, 1.0, 1.0], rs_vals)

# ── Binance ──────────────────────────────────────────────────────────────────

expected_keys = {"timestamp", "asset", "open", "high", "low", "close", "volume"}
check("Binance import ok", True, "imported")
check("Binance.OHLCV_SCHEMA keys", expected_keys == set(OHLCV_SCHEMA.keys()), set(OHLCV_SCHEMA.keys()))

# ── Frame ────────────────────────────────────────────────────────────────────

check("Frame.FRAME_COLUMNS len=11", len(FRAME_COLUMNS) == 11, len(FRAME_COLUMNS))

cfg = _build_config()
assets = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
check("Frame._build_config has Strategy_by_asset", "Strategy_by_asset" in cfg, list(cfg.keys()))
check("Frame._build_config has Indicator_by_asset", "Indicator_by_asset" in cfg, list(cfg.keys()))
check("Frame._build_config all 4 assets", all(a in cfg["Strategy_by_asset"] for a in assets), list(cfg["Strategy_by_asset"].keys()))

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{passed}/{total} passed")
