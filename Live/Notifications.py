"""Durable outbound notifications consumed by Major Tom's WhatsApp bridge."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_OUTBOX = Path("/var/lib/major-tom/outbox")
_SENSITIVE = re.compile(r"(?i)\b(signature|api[_-]?key|api[_-]?secret|authorization)=([^&\s]+)")


def _clean(message: str) -> str:
    return _SENSITIVE.sub(r"\1=<redacted>", " ".join(message.split()))[:2000]


def notify(kind: str, message: str) -> None:
    """Atomically queue one sanitized notification without blocking trading."""
    try:
        outbox = Path(os.getenv("MAJOR_TOM_OUTBOX_DIR", _DEFAULT_OUTBOX))
        outbox.mkdir(parents=True, exist_ok=True, mode=0o700)
        outbox.chmod(0o700)
        # ponytail: retain 1,000 pending messages; use a database queue if longer guaranteed delivery is required.
        for stale in sorted(outbox.glob("*.json"))[:-999]:
            stale.unlink(missing_ok=True)
        name = f"{time.time_ns()}-{uuid.uuid4().hex}.json"
        temporary = outbox / f".{name}.tmp"
        temporary.write_text(
            json.dumps({"kind": kind.upper(), "message": _clean(message), "created_at": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, outbox / name)
    except OSError:
        pass


class _MajorTomHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            notify("ERROR" if record.levelno >= logging.ERROR else "WARNING", f"{record.name}: {record.getMessage()}")
        except Exception:  # noqa: S110 - reporting this through logging would recurse into this handler
            pass


def install_logging_notifications() -> None:
    root = logging.getLogger()
    if not any(isinstance(handler, _MajorTomHandler) for handler in root.handlers):
        root.addHandler(_MajorTomHandler(logging.WARNING))
