"""Configuration and deterministic health boundary for the Baileys bridge."""

from __future__ import annotations

import json
import os
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path


def normalize_phone(value: str) -> str:
    """Normalize a phone number or WhatsApp JID to digits only."""
    return "".join(character for character in value if character.isdigit())


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    """Non-secret bridge configuration stored outside the repository."""

    admin_phone: str
    session_dir: Path
    state_file: Path

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "BridgeConfig":
        """Read the server-owned TOML file without accepting environment secrets."""
        config_path = Path(path or os.getenv("MAJOR_TOM_CONFIG", "/etc/hercules/major-tom/config.toml"))
        content = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
        whatsapp = content.get("whatsapp", {})
        return cls(
            admin_phone=normalize_phone(str(whatsapp.get("admin_phone", ""))),
            session_dir=Path(str(whatsapp.get("session_dir", "/etc/hercules/major-tom/whatsapp-session"))),
            state_file=Path(str(whatsapp.get("state_file", "/var/lib/major-tom/whatsapp-state.json"))),
        )


def bridge_health(path: str | Path, max_age_seconds: int = 300) -> dict[str, object]:
    """Read only the atomically-written bridge state consumed by the watchdog."""
    state_path = Path(path)
    try:
        state = json.loads(state_path.read_text())
        fresh = (time.time() - state_path.stat().st_mtime) <= max_age_seconds
    except (OSError, json.JSONDecodeError):
        return {"healthy": False, "reason": "state_unavailable"}
    required = ("connected", "paired", "session_readable", "reconnect_healthy")
    healthy = fresh and all(state.get(key) is True for key in required)
    return {"healthy": healthy, **{key: state.get(key, False) for key in required},
            "last_inbound_at": state.get("last_inbound_at"), "last_outbound_at": state.get("last_outbound_at"),
            "pairing_code": state.get("pairing_code"), "fresh": fresh, "reason": state.get("reason")}
