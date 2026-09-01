"""Deterministic watchdog for Major Tom and Hercules."""
import os
import time

from .audit import _health, _service_state
from .whatsapp_bridge import bridge_health


def watchdog(config=None):
    """Check process, web, DB configuration, and audit freshness read-only."""
    config = config or {}
    max_age = int(config.get("max_audit_age", os.getenv("MAJOR_TOM_MAX_AUDIT_AGE", "93600")))
    audit_file = config.get("audit_file", os.getenv("MAJOR_TOM_AUDIT_FILE", "/var/lib/major-tom/last-audit"))
    db_url = config.get("db_health_url", os.getenv("MAJOR_TOM_DB_HEALTH_URL", ""))
    try:
        audit_age = time.time() - os.stat(audit_file).st_mtime
    except OSError:
        audit_age = None
    checks = {"major_tom": _service_state(config.get("major_tom_timer", "major-tom.timer")),
              "hercules": _service_state(config.get("hercules_service", os.getenv("HERCULES_SERVICE", "hercules-dashboard.service"))),
              "web": _health(config.get("health_url", os.getenv("HERCULES_HEALTH_URL", "http://127.0.0.1:8000/health"))),
              "db_configured": bool(db_url or os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL")),
              "whatsapp": bridge_health(config.get("whatsapp_state_file", os.getenv("MAJOR_TOM_WHATSAPP_STATE_FILE", "/var/lib/major-tom/whatsapp-state.json")), int(config.get("whatsapp_max_state_age", os.getenv("MAJOR_TOM_WHATSAPP_MAX_STATE_AGE", "300")))),
              "audit_age_seconds": audit_age}
    checks["audit_fresh"] = audit_age is not None and audit_age <= max_age
    checks["ok"] = all((checks["major_tom"]["active"], checks["hercules"]["active"], checks["web"]["ok"], checks["db_configured"], checks["whatsapp"]["healthy"], checks["audit_fresh"]))
    return checks
