"""Python interface to Rust Strategy core — Phase 5 implementation."""
import polars as pl


def evaluate(frame: pl.DataFrame) -> pl.DataFrame:
    """Pass Hercules Frame through Rust core, return frame with BuildResult columns."""
    raise NotImplementedError("Strategy.evaluate — Phase 5")
