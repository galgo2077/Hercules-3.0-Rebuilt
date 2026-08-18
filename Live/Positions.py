"""Position tracking — fetch from exchange, compute signed exposure."""
from __future__ import annotations

from dataclasses import dataclass, field

from Live._client import BinanceClient


@dataclass
class Position:
    asset: str
    side: str  # LONG | SHORT | FLAT
    size_usdt: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float

    @property
    def is_flat(self) -> bool:
        return self.side == "FLAT" or self.size_usdt < 0.01


class PositionTracker:
    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}

    def fetch(self, client: BinanceClient) -> None:
        raw = client.get("/fapi/v2/positionRisk")
        for p in raw:
            symbol = p["symbol"]
            amt = float(p["positionAmt"])
            mark = float(p["markPrice"])
            entry = float(p["entryPrice"])
            upnl = float(p["unRealizedProfit"])
            if abs(amt) < 1e-9:
                side, usdt = "FLAT", 0.0
            elif amt > 0:
                side, usdt = "LONG", abs(amt) * mark
            else:
                side, usdt = "SHORT", abs(amt) * mark
            self._positions[symbol] = Position(symbol, side, usdt, entry, mark, upnl)

    def get(self, asset: str) -> Position:
        return self._positions.get(
            asset, Position(asset, "FLAT", 0.0, 0.0, 0.0, 0.0)
        )

    def all(self) -> dict[str, Position]:
        return dict(self._positions)

    def exposure(self, asset: str, allocated_usdt: float) -> float:
        """Signed exposure: +1.0 = full long, -1.0 = full short, 0 = flat."""
        if allocated_usdt < 0.01:
            return 0.0
        p = self.get(asset)
        if p.side == "LONG":
            return p.size_usdt / allocated_usdt
        if p.side == "SHORT":
            return -p.size_usdt / allocated_usdt
        return 0.0

    def as_exposure_dict(self, allocations: dict[str, float]) -> dict[str, float]:
        return {asset: self.exposure(asset, alloc) for asset, alloc in allocations.items()}
