/// Build stage — single final strategy decision from evaluated scores.
/// Upstream evaluates. Build decides. No exchange access here.
use pyo3::prelude::*;

#[pyclass]
#[derive(Debug, Clone)]
pub struct BuildResult {
    #[pyo3(get)]
    pub timestamp_ms: i64,
    #[pyo3(get)]
    pub asset: String,
    #[pyo3(get)]
    pub action: String,
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
            "BuildResult({} {} {} side={} entry={} exit={})",
            self.asset, self.action, self.reason, self.side, self.entry_allowed, self.exit_required
        )
    }
}

/// Build final trading decision from long/short scores.
/// action: Hold | Entry | Exit
/// side: Long | Short | None
#[pyfunction]
pub fn build_decision(
    timestamp_ms: i64,
    asset: &str,
    long_score: f64,
    short_score: f64,
    current_exposure: f64,
    target_exposure_long: f64,
    target_exposure_short: f64,
) -> BuildResult {
    let (action, side, target_exposure, entry_allowed, exit_required, reason) =
        if long_score > 0.0 && short_score == 0.0 {
            let delta = target_exposure_long - current_exposure;
            if delta.abs() < 1e-9 {
                ("Hold", "Long", current_exposure, false, false, "hold_long")
            } else {
                ("Entry", "Long", target_exposure_long, true, false, "entry_long")
            }
        } else if short_score > 0.0 && long_score == 0.0 {
            let delta = (-target_exposure_short) - current_exposure;
            if delta.abs() < 1e-9 {
                ("Hold", "Short", current_exposure, false, false, "hold_short")
            } else {
                ("Entry", "Short", -target_exposure_short, true, false, "entry_short")
            }
        } else if current_exposure.abs() > 1e-9 {
            ("Exit", "None", 0.0, false, true, "exit_flat")
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
