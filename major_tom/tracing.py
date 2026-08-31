"""Non-blocking execution trace recorder for Hercules engines."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import uuid
from pathlib import Path
from time import perf_counter
from typing import Any

from major_tom.models import TraceStage, utc_now
from major_tom.store import MajorTomStore

log = logging.getLogger(__name__)


class ExecutionTrace:
    """One strategy-to-position trace. Recorder errors never alter trading decisions."""

    def __init__(self, environment: str, strategy: str, symbol: str, input_value: Any) -> None:
        self.trace_id = str(uuid.uuid4())
        self.environment = environment
        self.strategy = strategy
        self.symbol = symbol
        self.input_hash = hashlib.sha256(json.dumps(input_value, sort_keys=True, default=str).encode()).hexdigest()
        self.started = perf_counter()
        self._path = Path(os.environ.get("MAJOR_TOM_TRACE_DB", ".hercules/major-tom.sqlite3"))

    def stage(self, decision: str, reason: str, expected: Any = None, actual: Any = None, error: Exception | None = None) -> None:
        """Append evidence. Trace storage failure only logs; execution stays independent."""
        store = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            store = MajorTomStore(self._path)
            store.record_trace(TraceStage(
                self.trace_id, utc_now(), self.environment, self.strategy, self.symbol, self.input_hash,
                decision, reason, expected, actual, round((perf_counter() - self.started) * 1000, 2),
                str(error) if error else None,
            ))
            if error is not None:
                incident = store.detect_missed_execution(self.trace_id)
                if incident:
                    log.critical("Major Tom %s: %s", incident.incident_id, incident.title)
        except (OSError, sqlite3.Error, TypeError, ValueError, json.JSONDecodeError) as exc:
            log.error("Major Tom trace persistence failed: %s", exc)
        finally:
            if store is not None:
                store.close()
