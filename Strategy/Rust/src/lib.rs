use pyo3::prelude::*;

mod core;
mod build;

#[pymodule]
fn _strategy(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<core::StrategyInput>()?;
    m.add_class::<build::BuildResult>()?;
    m.add_function(wrap_pyfunction!(core::evaluate, m)?)?;
    m.add_function(wrap_pyfunction!(build::build_decision, m)?)?;
    Ok(())
}
