/// Strategy evaluation — deterministic core.
/// Receives per-candle frame data, returns scored state.
/// No I/O, no config reads, no side effects.
use pyo3::prelude::*;

#[pyclass]
#[derive(Debug, Clone)]
pub struct StrategyInput {
    #[pyo3(get, set)]
    pub timestamp_ms: i64,
    #[pyo3(get, set)]
    pub asset: String,
    #[pyo3(get, set)]
    pub direction: Option<String>,
    #[pyo3(get, set)]
    pub volatility_regime: i8,
    #[pyo3(get, set)]
    pub final_signal: i8,
    #[pyo3(get, set)]
    pub short_trend_similarity: f32,
    #[pyo3(get, set)]
    pub slope: f64,
    #[pyo3(get, set)]
    pub bars_in_direction: i64,
    #[pyo3(get, set)]
    pub bars_bearish: i64,
    #[pyo3(get, set)]
    pub warmup_complete: bool,
}

#[pymethods]
impl StrategyInput {
    #[new]
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        timestamp_ms: i64,
        asset: String,
        direction: Option<String>,
        volatility_regime: i8,
        final_signal: i8,
        short_trend_similarity: f32,
        slope: f64,
        bars_in_direction: i64,
        bars_bearish: i64,
        warmup_complete: bool,
    ) -> Self {
        Self {
            timestamp_ms,
            asset,
            direction,
            volatility_regime,
            final_signal,
            short_trend_similarity,
            slope,
            bars_in_direction,
            bars_bearish,
            warmup_complete,
        }
    }
}

/// Evaluate one candle's readiness for entry/exit signals.
/// Returns raw score tuple (long_score, short_score) in [0,1].
/// Placeholder — real logic migrated from Strategy/strategy.py in Phase 5.
#[pyfunction]
pub fn evaluate(input: &StrategyInput) -> (f64, f64) {
    if !input.warmup_complete {
        return (0.0, 0.0);
    }
    let long_score = if input.final_signal == 1 { 1.0 } else { 0.0 };
    let short_score = if input.final_signal == -1 { 1.0 } else { 0.0 };
    (long_score, short_score)
}
