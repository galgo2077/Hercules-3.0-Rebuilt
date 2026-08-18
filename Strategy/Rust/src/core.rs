/// Strategy evaluation — deterministic core.
/// Receives per-candle frame data + current position state, returns scored signals.
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
    pub final_signal: i8,
    #[pyo3(get, set)]
    pub short_trend_similarity: f32,
    /// NaN when slope column is null (no slope during warmup).
    #[pyo3(get, set)]
    pub slope: f64,
    #[pyo3(get, set)]
    pub warmup_complete: bool,
}

#[pymethods]
impl StrategyInput {
    #[new]
    pub fn new(
        timestamp_ms: i64,
        asset: String,
        direction: Option<String>,
        final_signal: i8,
        short_trend_similarity: f32,
        slope: f64,
        warmup_complete: bool,
    ) -> Self {
        Self {
            timestamp_ms,
            asset,
            direction,
            final_signal,
            short_trend_similarity,
            slope,
            warmup_complete,
        }
    }
}

/// Returns true when signal would open or reverse a position.
/// Mirrors shared/signal_transition.py::is_new_entry.
#[inline]
pub fn is_new_entry(current_side: i8, signal: i8) -> bool {
    signal != 0 && current_side != signal
}

/// Evaluate one candle's readiness for a new entry signal.
///
/// current_side: current position side for this asset (-1/0/1).
/// require_slope_confirmation: from Strategy.toml conditions.
///
/// Returns (long_score, short_score) in {0.0, 1.0}.
/// Both zero means no tradeable signal this bar.
#[pyfunction]
pub fn evaluate(
    input: &StrategyInput,
    current_side: i8,
    require_slope_confirmation: bool,
) -> (f64, f64) {
    if !input.warmup_complete || input.final_signal == 0 {
        return (0.0, 0.0);
    }
    if !is_new_entry(current_side, input.final_signal) {
        return (0.0, 0.0);
    }
    if require_slope_confirmation {
        let slope_ok = input.slope.is_finite()
            && if input.final_signal == 1 {
                input.slope > 0.0
            } else {
                input.slope < 0.0
            };
        if !slope_ok {
            return (0.0, 0.0);
        }
    }
    if input.final_signal == 1 {
        (1.0, 0.0)
    } else {
        (0.0, 1.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_input(signal: i8, slope: f64) -> StrategyInput {
        StrategyInput::new(0, "BTCUSDT".into(), Some("BULLISH".into()), signal, 0.5, slope, true)
    }

    #[test]
    fn no_signal_when_flat() {
        let inp = make_input(0, 0.1);
        assert_eq!(evaluate(&inp, 0, false), (0.0, 0.0));
    }

    #[test]
    fn long_entry_flat_no_slope_gate() {
        let inp = make_input(1, f64::NAN);
        assert_eq!(evaluate(&inp, 0, false), (1.0, 0.0));
    }

    #[test]
    fn long_entry_requires_positive_slope() {
        let inp_pos = make_input(1, 0.01);
        let inp_neg = make_input(1, -0.01);
        assert_eq!(evaluate(&inp_pos, 0, true), (1.0, 0.0));
        assert_eq!(evaluate(&inp_neg, 0, true), (0.0, 0.0));
    }

    #[test]
    fn short_entry_requires_negative_slope() {
        let inp_neg = make_input(-1, -0.01);
        let inp_pos = make_input(-1, 0.01);
        assert_eq!(evaluate(&inp_neg, 0, true), (0.0, 1.0));
        assert_eq!(evaluate(&inp_pos, 0, true), (0.0, 0.0));
    }

    #[test]
    fn same_side_no_reentry() {
        let inp = make_input(1, 0.1);
        // already long, same signal → no new entry
        assert_eq!(evaluate(&inp, 1, false), (0.0, 0.0));
    }

    #[test]
    fn reversal_fires() {
        // currently short, long signal → reversal allowed
        let inp = make_input(1, 0.1);
        assert_eq!(evaluate(&inp, -1, false), (1.0, 0.0));
    }

    #[test]
    fn warmup_blocks_signal() {
        let mut inp = make_input(1, 0.1);
        inp.warmup_complete = false;
        assert_eq!(evaluate(&inp, 0, false), (0.0, 0.0));
    }
}
