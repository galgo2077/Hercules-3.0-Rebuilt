from major_tom.store import MajorTomStore
from major_tom.tracing import ExecutionTrace


def test_failed_submission_creates_high_incident(tmp_path, monkeypatch):
    database = tmp_path / "traces.sqlite3"
    monkeypatch.setenv("MAJOR_TOM_TRACE_DB", str(database))
    trace = ExecutionTrace("TESTNET", "Hercules", "BTCUSDT", {"action": "Entry"})
    trace.stage("signal_generated", "entry")
    trace.stage("order_failed", "Binance rejected", error=RuntimeError("timeout"))
    store = MajorTomStore(database)
    assert store.detect_missed_execution(trace.trace_id).severity == "HIGH"
