"""Position tracking — fetch from exchange, compute signed exposure."""

from __future__ import annotations

from dataclasses import dataclass

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
        self._positions: dict[tuple[str, str], Position] = {}

    def fetch(self, client: BinanceClient) -> None:
        raw = client.get("/fapi/v2/positionRisk")
        if not isinstance(raw, list):
            raise RuntimeError("exchange returned invalid position state")
        self._positions.clear()
        for p in raw:
            symbol = p["symbol"]
            amt = float(p["positionAmt"])
            mark = float(p["markPrice"])
            entry = float(p["entryPrice"])
            upnl = float(p["unRealizedProfit"])
            position_side = str(p.get("positionSide", "BOTH"))
            if position_side == "BOTH":
                if abs(amt) < 1e-9:
                    continue
                position_side = "LONG" if amt > 0 else "SHORT"
            if position_side not in {"LONG", "SHORT"}:
                raise RuntimeError(f"invalid exchange position side: {position_side}")
            side = position_side if abs(amt) >= 1e-9 else "FLAT"
            self._positions[(symbol, position_side)] = Position(symbol, side, abs(amt) * mark, entry, mark, upnl)

    def get(self, asset: str, side: str | None = None) -> Position:
        if side is not None:
            return self._positions.get((asset, side), Position(asset, "FLAT", 0.0, 0.0, 0.0, 0.0))
        open_positions = [position for candidate in ("LONG", "SHORT") if (position := self._positions.get((asset, candidate))) and not position.is_flat]
        if len(open_positions) > 1:
            raise RuntimeError(f"both LONG and SHORT are open for {asset}")
        if open_positions:
            return open_positions[0]
        return Position(asset, "FLAT", 0.0, 0.0, 0.0, 0.0)

    def all(self) -> dict[tuple[str, str], Position]:
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
