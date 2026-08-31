"""Operational audit for Hercules."""
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

EXPECTED_ERRORS = ("authentication", "unauthorized", "insufficient", "invalid input", "validation")

def _run(command):
    """Run a read-only command and return its trimmed output."""
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603 -- fixed read-only command list
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def _service_state(service):
    """Read a systemd service state without changing it."""
    code, stdout, stderr = _run(["systemctl", "is-active", service])
    return {"active": code == 0 and stdout == "active", "output": stdout or stderr}

def _health(url, timeout=5):
    """Read an HTTP health endpoint and return status and latency."""
    started = time.monotonic()
    if urlparse(url).scheme not in {"http", "https"}:
        return {"ok": False, "error": "health URL must be HTTP(S)", "latency_ms": 0}
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 -- scheme checked above
            return {"ok": 200 <= response.status < 400, "status": response.status,
                    "latency_ms": round((time.monotonic() - started) * 1000, 2)}
    except Exception as exc:  # diagnostic boundary: health must never crash audit
        return {"ok": False, "error": str(exc),
                "latency_ms": round((time.monotonic() - started) * 1000, 2)}

def _git_state(repo):
    """Read repository SHA and cleanliness without altering Git state."""
    sha_code, sha, sha_err = _run(["git", "-C", repo, "rev-parse", "HEAD"])
    dirty_code, dirty, dirty_err = _run(["git", "-C", repo, "status", "--porcelain"])
    return {"sha": sha if sha_code == 0 else None, "clean": dirty_code == 0 and not dirty,
            "error": sha_err or dirty_err or None}

def _expected_error(line):
    """Identify expected user/input failures that must not alert."""
    lowered = line.lower()
    return any(term in lowered for term in EXPECTED_ERRORS)

def audit(config=None, deep=False):
    """Collect operational evidence; deep mode adds static repository evidence."""
    config = config or {}
    service = config.get("service", os.getenv("HERCULES_SERVICE", "hercules-dashboard.service"))
    url = config.get("health_url", os.getenv("HERCULES_HEALTH_URL", "http://127.0.0.1:8000/health"))
    repo = config.get("repo", os.getenv("HERCULES_REPO", os.getcwd()))
    evidence = {"service": _service_state(service), "web": _health(url), "git": _git_state(repo),
                "timestamp": int(time.time()), "environment": os.getenv("HERCULES_ENVIRONMENT", "UNKNOWN"),
                "audit_kind": "deep" if deep else "daily"}
    if deep:
        code, stdout, stderr = _run(["git", "-C", repo, "fsck", "--no-dangling"])
        evidence["repository_integrity"] = {"ok": code == 0, "output": stdout or stderr}
        code, stdout, stderr = _run(["git", "-C", repo, "log", "-1", "--format=%H %cI %s"])
        evidence["latest_commit"] = {"ok": code == 0, "output": stdout or stderr}
    evidence["ok"] = evidence["service"]["active"] and evidence["web"]["ok"]
    if deep:
        evidence["ok"] = evidence["ok"] and evidence["repository_integrity"]["ok"]
    evidence["severity"] = "INFO" if evidence["ok"] else "ERROR"
    audit_file = Path(config.get("audit_file", os.getenv("MAJOR_TOM_AUDIT_FILE", ".hercules/major-tom-audit.json")))
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    audit_file.write_text(json.dumps(evidence, sort_keys=True))
    return evidence
