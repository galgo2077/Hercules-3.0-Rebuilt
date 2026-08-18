"""Per-asset rolling candle buffer — ingest closed candles, gate strategy-ready."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class Candle:
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    asset: str

    @property
    def ts(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp_ms / 1000, tz=timezone.utc)


def _parse(asset: str, k: dict[str, Any]) -> Candle:
    """Parse a Binance kline dict (WebSocket or REST) into a Candle."""
    return Candle(
        timestamp_ms=int(k.get("t", k.get("timestamp", 0))),
        open=float(k.get("o", k.get("open", 0))),
        high=float(k.get("h", k.get("high", 0))),
        low=float(k.get("l", k.get("low", 0))),
        close=float(k.get("c", k.get("close", 0))),
        volume=float(k.get("v", k.get("volume", 0))),
        asset=asset,
    )


class CandleBuffer:
    """Thread-safe rolling window of closed candles per asset."""

    def __init__(self, capacity: int = 500) -> None:
        self._capacity = capacity
        self._buf: dict[str, deque[Candle]] = {}

    @property
    def capacity(self) -> int:
        return self._capacity

    def _ensure(self, asset: str) -> deque[Candle]:
        if asset not in self._buf:
            self._buf[asset] = deque(maxlen=self._capacity)
        return self._buf[asset]

    def ingest(self, asset: str, kline: dict[str, Any], *, is_closed: bool = True) -> bool:
        """Add a candle to the buffer. Returns True if closed and stored."""
        if not is_closed:
            return False
        c = _parse(asset, kline)
        buf = self._ensure(asset)
        if buf and buf[-1].timestamp_ms == c.timestamp_ms:
            buf[-1] = c  # dedup same candle
        else:
            buf.append(c)
        return True

    def ingest_ws(self, asset: str, msg: dict[str, Any]) -> bool:
        """Parse a raw Binance WebSocket kline message and ingest if closed."""
        k = msg.get("data", msg).get("k", msg.get("k", {}))
        return self.ingest(asset, k, is_closed=bool(k.get("x", False)))

    def ready(self, asset: str, min_bars: int = 200) -> bool:
        return len(self._buf.get(asset, [])) >= min_bars

    def get(self, asset: str) -> list[Candle]:
        return list(self._buf.get(asset, []))

    def to_dicts(self, asset: str) -> list[dict[str, Any]]:
        return [{"timestamp": c.timestamp_ms, "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume, "asset": c.asset} for c in self._buf.get(asset, [])]

    def health(self, asset: str) -> dict[str, Any]:
        buf = self._buf.get(asset, deque())
        return {
            "asset": asset,
            "bars": len(buf),
            "latest_ts": buf[-1].ts.isoformat() if buf else None,
            "ready": self.ready(asset),
        }

    def reset(self, asset: str | None = None) -> None:
        if asset:
            self._buf.pop(asset, None)
        else:
            self._buf.clear()
