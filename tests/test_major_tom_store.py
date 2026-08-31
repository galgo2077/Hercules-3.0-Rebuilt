from major_tom import MajorTomStore, TraceStage


def stage(trace_id: str, decision: str) -> TraceStage:
    return TraceStage(trace_id, "2026-01-01T00:00:00+00:00", "TESTNET", "demo", "BTCUSDT", "hash", decision, "ok")


def test_trace_is_durable_and_detects_missed_execution(tmp_path):
    path = tmp_path / "major-tom.sqlite3"
    store = MajorTomStore(path)
    store.record_trace(stage("t1", "signal_generated"))
    incident = store.detect_missed_execution("t1")
    assert incident and incident.severity == "HIGH"
    store.close()
    reopened = MajorTomStore(path)
    assert reopened.trace("t1")[0].decision == "signal_generated"
    assert reopened.get_incident(incident.incident_id).state == "DETECTED"


def test_submitted_order_does_not_raise_incident(tmp_path):
    store = MajorTomStore(tmp_path / "db")
    store.record_trace(stage("t2", "signal_generated"))
    store.record_trace(stage("t2", "order_submitted"))
    assert store.detect_missed_execution("t2") is None


def test_incident_state_machine_rejects_skips(tmp_path):
    store = MajorTomStore(tmp_path / "db")
    incident = store.create_incident("HIGH", "failure")
    try:
        store.transition(incident.incident_id, "RESOLVED")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid transition accepted")
    assert store.transition(incident.incident_id, "INVESTIGATING").state == "INVESTIGATING"
