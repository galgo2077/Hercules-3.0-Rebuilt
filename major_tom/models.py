"""Durable Major Tom domain records."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

INCIDENT_STATES = (
    "DETECTED", "INVESTIGATING", "PLAN_READY", "WAITING_APPROVAL",
    "APPROVED", "IMPLEMENTING", "TESTING", "VERIFYING",
    "FIXED_PENDING_RUNTIME_VERIFICATION", "RESOLVED", "REJECTED", "FAILED",
)


def utc_now() -> str:
    """Return an unambiguous UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class TraceStage:
    """One observable stage in a trade execution trace."""
    trace_id: str
    timestamp: str
    environment: str
    strategy: str
    symbol: str
    input_hash: str
    decision: str
    reason: str
    expected_output: Any = None
    actual_output: Any = None
    latency_ms: float | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Incident:
    """A persisted, auditable Major Tom incident."""
    incident_id: str
    state: str
    severity: str
    title: str
    trace_id: str | None = None
    environment: str | None = None
    evidence: Any = None
    created_at: str = ""
    updated_at: str = ""

