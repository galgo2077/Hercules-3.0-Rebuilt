"""Small SQLite store for Major Tom traces and incidents."""

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .models import INCIDENT_STATES, Incident, TraceStage, utc_now

_TRANSITIONS = {
    "DETECTED": {"INVESTIGATING", "REJECTED", "FAILED"},
    "INVESTIGATING": {"PLAN_READY", "FAILED"},
    "PLAN_READY": {"WAITING_APPROVAL", "FAILED"},
    "WAITING_APPROVAL": {"APPROVED", "REJECTED", "FAILED"},
    "APPROVED": {"IMPLEMENTING", "FAILED"},
    "IMPLEMENTING": {"TESTING", "FAILED"},
    "TESTING": {"VERIFYING", "FAILED"},
    "VERIFYING": {"FIXED_PENDING_RUNTIME_VERIFICATION", "RESOLVED", "FAILED"},
    "FIXED_PENDING_RUNTIME_VERIFICATION": {"VERIFYING", "RESOLVED", "FAILED"},
    "RESOLVED": set(), "REJECTED": set(), "FAILED": set(),
}


def _json(value: Any) -> str | None:
    """Encode optional evidence without losing structured values."""
    return None if value is None else json.dumps(value, sort_keys=True, default=str)


class MajorTomStore:
    """SQLite-backed append-only trace and stateful incident repository."""

    def __init__(self, path: str | Path):
        """Open a database and create its tables."""
        self.path = str(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS traces (
              id INTEGER PRIMARY KEY, trace_id TEXT NOT NULL, timestamp TEXT NOT NULL,
              environment TEXT NOT NULL, strategy TEXT NOT NULL, symbol TEXT NOT NULL,
              input_hash TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
              expected_output TEXT, actual_output TEXT, latency_ms REAL, error TEXT
            );
            CREATE INDEX IF NOT EXISTS traces_lookup ON traces(trace_id, decision);
            CREATE TABLE IF NOT EXISTS incidents (
              incident_id TEXT PRIMARY KEY, state TEXT NOT NULL, severity TEXT NOT NULL,
              title TEXT NOT NULL, trace_id TEXT, environment TEXT, evidence TEXT,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
        """)
        self.connection.commit()

    def close(self) -> None:
        """Close the database connection."""
        self.connection.close()

    def record_trace(self, stage: TraceStage) -> None:
        """Append a trace stage and preserve every observed event."""
        self.connection.execute("INSERT INTO traces VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?,?)", (
            stage.trace_id, stage.timestamp, stage.environment, stage.strategy, stage.symbol,
            stage.input_hash, stage.decision, stage.reason, _json(stage.expected_output),
            _json(stage.actual_output), stage.latency_ms, stage.error,
        ))
        self.connection.commit()

    def trace(self, trace_id: str) -> list[TraceStage]:
        """Read a trace in event order."""
        rows = self.connection.execute("SELECT * FROM traces WHERE trace_id=? ORDER BY id", (trace_id,))
        return [TraceStage(r["trace_id"], r["timestamp"], r["environment"], r["strategy"], r["symbol"],
                           r["input_hash"], r["decision"], r["reason"],
                           json.loads(r["expected_output"]) if r["expected_output"] else None,
                           json.loads(r["actual_output"]) if r["actual_output"] else None,
                           r["latency_ms"], r["error"]) for r in rows]

    def detect_missed_execution(self, trace_id: str) -> Incident | None:
        """Create HIGH incident when a signal exists without submitted order."""
        stages = self.trace(trace_id)
        decisions = {stage.decision for stage in stages}
        if "signal_generated" not in decisions or "order_submitted" in decisions:
            return None
        existing = self.connection.execute("SELECT incident_id FROM incidents WHERE trace_id=? AND state NOT IN ('RESOLVED','REJECTED')", (trace_id,)).fetchone()
        if existing:
            return self.get_incident(existing["incident_id"])
        stage = stages[0]
        return self.create_incident("HIGH", "Signal sent but trade not executed", trace_id, stage.environment,
                                    {"invariant": "signal_generated_without_order_submitted"})

    def create_incident(self, severity: str, title: str, trace_id: str | None = None,
                        environment: str | None = None, evidence: Any = None) -> Incident:
        """Persist a newly detected incident."""
        now = utc_now()
        incident = Incident(f"MT-{uuid.uuid4().hex[:12].upper()}", "DETECTED", severity, title,
                            trace_id, environment, evidence, now, now)
        self.connection.execute("INSERT INTO incidents VALUES(?,?,?,?,?,?,?,?,?)",
                                (incident.incident_id, incident.state, incident.severity, incident.title,
                                 incident.trace_id, incident.environment, _json(evidence), now, now))
        self.connection.commit()
        return incident

    def get_incident(self, incident_id: str) -> Incident | None:
        """Fetch one incident by its stable identifier."""
        r = self.connection.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,)).fetchone()
        if not r:
            return None
        return Incident(r["incident_id"], r["state"], r["severity"], r["title"], r["trace_id"],
                        r["environment"], json.loads(r["evidence"]) if r["evidence"] else None,
                        r["created_at"], r["updated_at"])

    def transition(self, incident_id: str, state: str) -> Incident:
        """Move an incident through the exact approved state machine."""
        if state not in INCIDENT_STATES:
            raise ValueError(f"unknown incident state: {state}")
        incident = self.get_incident(incident_id)
        if incident is None:
            raise KeyError(incident_id)
        if state not in _TRANSITIONS[incident.state]:
            raise ValueError(f"invalid transition {incident.state} -> {state}")
        now = utc_now()
        self.connection.execute("UPDATE incidents SET state=?, updated_at=? WHERE incident_id=?", (state, now, incident_id))
        self.connection.commit()
        return self.get_incident(incident_id)  # type: ignore[return-value]

