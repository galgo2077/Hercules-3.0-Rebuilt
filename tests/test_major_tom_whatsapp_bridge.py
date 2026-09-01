from __future__ import annotations

import json

from major_tom.whatsapp_bridge import BridgeConfig, bridge_health, normalize_phone


def test_normalize_phone_accepts_jid_and_punctuation() -> None:
    assert normalize_phone("+52 (55) 1234-5678@s.whatsapp.net") == "525512345678"


def test_bridge_config_is_server_owned(tmp_path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("[whatsapp]\nadmin_phone = '+52 55 1234 5678'\n")
    config = BridgeConfig.from_file(config_file)
    assert config.admin_phone == "525512345678"
    assert str(config.session_dir).startswith("/etc/hercules/")


def test_bridge_health_requires_connection_and_pairing(tmp_path) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"connected": True, "paired": True, "session_readable": True, "reconnect_healthy": True}))
    assert bridge_health(state_file)["healthy"]
    state_file.write_text(json.dumps({"connected": True, "paired": False, "session_readable": True, "reconnect_healthy": True}))
    assert not bridge_health(state_file)["healthy"]


def test_bridge_health_rejects_stale_state(tmp_path) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"connected": True, "paired": True, "session_readable": True, "reconnect_healthy": True}))
    assert not bridge_health(state_file, max_age_seconds=-1)["healthy"]
