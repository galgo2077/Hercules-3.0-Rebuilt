"""Position reconciliation — detect and resolve divergence between local state and exchange."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from Live._client import BinanceClient
from Live.Positions import PositionTracker

log = logging.getLogger(__name__)

_FLAT_THRESHOLD = 0.01  # USDT — positions smaller than this treated as flat


@dataclass(frozen=True, slots=True)
class Mismatch:
    asset: str
    position_side: str
    local_side: str  # LONG | SHORT | FLAT
    exchange_side: str
    local_usdt: float
    exchange_usdt: float


def reconcile(
    tracker: PositionTracker,
    client: BinanceClient,
    assets: list[str] | None = None,
) -> list[Mismatch]:
    """Compare local PositionTracker against exchange, return list of divergences."""
    # fetch fresh exchange state into a temp tracker
    live = PositionTracker()
    live.fetch(client)
    assets = sorted(set(assets or ()) | {asset for asset, _ in tracker.all()} | {asset for asset, _ in live.all()})

    mismatches: list[Mismatch] = []
    for asset in assets:
        for side in ("LONG", "SHORT"):
            local = tracker.get(asset, side)
            exchange = live.get(asset, side)
            if local.side != exchange.side or abs(local.size_usdt - exchange.size_usdt) > _FLAT_THRESHOLD:
                mismatch = Mismatch(
                    asset=asset,
                    position_side=side,
                    local_side=local.side,
                    exchange_side=exchange.side,
                    local_usdt=local.size_usdt,
                    exchange_usdt=exchange.size_usdt,
                )
                log.warning("reconcile mismatch %s %s: local=%.2f exchange=%.2f", asset, side, local.size_usdt, exchange.size_usdt)
                mismatches.append(mismatch)

    return mismatches


def resolve(mismatch: Mismatch, client: BinanceClient) -> None:
    """Close any unexpected exchange position for the mismatched asset.

    Strategy: trust exchange state, update local tracker after resolution.
    Unexpected open → close it. Unexpected flat → no action (can't open without signal).
    """
    from Live.Orders import Long, Short

    asset = mismatch.asset
    ex_side = mismatch.position_side

    if mismatch.exchange_side == "LONG" and mismatch.local_side == "FLAT":
        log.warning("resolve: closing unexpected LONG on %s", asset)
        Long.exit(client, asset)

    elif mismatch.exchange_side == "SHORT" and mismatch.local_side == "FLAT":
        log.warning("resolve: closing unexpected SHORT on %s", asset)
        Short.exit(client, asset)

    elif ex_side == "FLAT" and mismatch.local_side != "FLAT":
        # exchange already flat — just update local knowledge, no order needed
        log.info("resolve: exchange is flat for %s, local was %s — syncing", asset, mismatch.local_side)


def sync_tracker(tracker: PositionTracker, client: BinanceClient, assets: list[str] | None = None) -> list[Mismatch]:
    """Reconcile, resolve all mismatches, then re-fetch to bring tracker current."""
    mismatches = reconcile(tracker, client, assets)
    for m in mismatches:
        resolve(m, client)
    if mismatches:
        tracker.fetch(client)
    return mismatches
