/// Build stage — final strategy decision from evaluated scores + position state.
/// Upstream evaluates. Build decides action type and exposure delta.
use pyo3::prelude::*;

#[pyclass]
#[derive(Debug, Clone)]
pub struct BuildResult {
    #[pyo3(get)]
    pub timestamp_ms: i64,
    #[pyo3(get)]
    pub asset: String,
    /// "Entry" | "Hold" | "Exit"
    #[pyo3(get)]
    pub action: String,
    /// "Long" | "Short" | "None"
    #[pyo3(get)]
    pub side: String,
    #[pyo3(get)]
    pub target_exposure: f64,
    #[pyo3(get)]
    pub exposure_delta: f64,
    #[pyo3(get)]
    pub entry_allowed: bool,
    #[pyo3(get)]
    pub exit_required: bool,
    #[pyo3(get)]
    pub reason: String,
}

#[pymethods]
impl BuildResult {
    pub fn __repr__(&self) -> String {
        format!(
            "BuildResult({} {} {} side={} δ={:.4})",
            self.asset, self.action, self.reason, self.side, self.exposure_delta
        )
    }
}

/// Build trading decision from evaluate() scores.
///
/// current_exposure: signed exposure fraction (positive=long, negative=short, 0=flat).
/// target_long / target_short: desired exposure magnitude for each side (from Portfolio.toml).
///
/// action semantics:
///   "Entry"  → open new position or reverse; entry_allowed=true.
///   "Hold"   → no change; existing position continues.
///   "Exit"   → opposing signal arrived while positioned; exit_required=true.
#[pyfunction]
pub fn build_decision(
    timestamp_ms: i64,
    asset: &str,
    long_score: f64,
    short_score: f64,
    current_exposure: f64,
    target_long: f64,
    target_short: f64,
) -> BuildResult {
    let has_long = long_score > 0.0;
    let has_short = short_score > 0.0;
    let is_long = current_exposure > 1e-9;
    let is_short = current_exposure < -1e-9;
    let is_flat = !is_long && !is_short;

    let (action, side, target_exposure, entry_allowed, exit_required, reason) = if has_long {
        let target = target_long;
        if is_short {
            ("Entry", "Long", target, true, true, "reversal_to_long")
        } else {
            ("Entry", "Long", target, true, false, "entry_long")
        }
    } else if has_short {
        let target = -target_short;
        if is_long {
            ("Entry", "Short", target, true, true, "reversal_to_short")
        } else {
            ("Entry", "Short", target, true, false, "entry_short")
        }
    } else if !is_flat {
        // no new signal while positioned — execution engine handles TP/SL
        ("Hold", if is_long { "Long" } else { "Short" }, current_exposure, false, false, "hold_in_position")
    } else {
        ("Hold", "None", 0.0, false, false, "hold_flat")
    };

    BuildResult {
        timestamp_ms,
        asset: asset.to_string(),
        action: action.to_string(),
        side: side.to_string(),
        target_exposure,
        exposure_delta: target_exposure - current_exposure,
        entry_allowed,
        exit_required,
        reason: reason.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn long_entry_from_flat() {
        let r = build_decision(0, "BTC", 1.0, 0.0, 0.0, 0.15, 0.15);
        assert_eq!(r.action, "Entry");
        assert_eq!(r.side, "Long");
        assert!(r.entry_allowed);
        assert!(!r.exit_required);
        assert!((r.target_exposure - 0.15).abs() < 1e-9);
    }

    #[test]
    fn short_entry_from_flat() {
        let r = build_decision(0, "BTC", 0.0, 1.0, 0.0, 0.15, 0.15);
        assert_eq!(r.action, "Entry");
        assert_eq!(r.side, "Short");
        assert!(r.entry_allowed);
        assert!((r.target_exposure - (-0.15)).abs() < 1e-9);
    }

    #[test]
    fn hold_in_long_no_signal() {
        let r = build_decision(0, "BTC", 0.0, 0.0, 0.15, 0.15, 0.15);
        assert_eq!(r.action, "Hold");
        assert_eq!(r.side, "Long");
        assert!(!r.entry_allowed);
    }

    #[test]
    fn reversal_long_to_short() {
        let r = build_decision(0, "BTC", 0.0, 1.0, 0.15, 0.15, 0.15);
        assert_eq!(r.action, "Entry");
        assert_eq!(r.side, "Short");
        assert!(r.entry_allowed);
        assert!(r.exit_required);
        assert_eq!(r.reason, "reversal_to_short");
    }

    #[test]
    fn reversal_short_to_long() {
        let r = build_decision(0, "BTC", 1.0, 0.0, -0.15, 0.15, 0.15);
        assert_eq!(r.action, "Entry");
        assert_eq!(r.side, "Long");
        assert!(r.entry_allowed);
        assert!(r.exit_required);
        assert_eq!(r.reason, "reversal_to_long");
    }

    #[test]
    fn hold_flat_no_signal() {
        let r = build_decision(0, "BTC", 0.0, 0.0, 0.0, 0.15, 0.15);
        assert_eq!(r.action, "Hold");
        assert_eq!(r.side, "None");
        assert!(!r.entry_allowed);
    }
}
