"""Binance OHLCV market-data I/O — Phase 4 implementation."""
import polars as pl


OHLCV_SCHEMA = {
    "timestamp": pl.Datetime("ms", "UTC"),
    "asset": pl.String,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
}


def fetch_historical(
    assets: list[str],
    start: str,
    end: str,
    interval: str = "1h",
) -> pl.DataFrame:
    raise NotImplementedError("Binance.fetch_historical — Phase 4")


def subscribe_live(assets: list[str], interval: str = "1h"):
    raise NotImplementedError("Binance.subscribe_live — Phase 4")
