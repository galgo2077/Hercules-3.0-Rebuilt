"""Codex CLI runner. Uses logged-in CLI session, never an API key."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def run(prompt: str, repository: Path, timeout_seconds: int = 900) -> subprocess.CompletedProcess[str]:
    """Run one bounded Codex CLI turn from the incident repository."""
    environment = {key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"}
    executable = shutil.which("codex")
    if not executable:
        raise FileNotFoundError("Codex CLI not installed")
    return subprocess.run(  # noqa: S603 -- executable resolved from local PATH, prompt enters Codex as data
        [executable, "exec", prompt],
        cwd=repository,
        env=environment,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
