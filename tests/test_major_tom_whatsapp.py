from __future__ import annotations

import hashlib
import hmac

from major_tom.whatsapp import authorized_message, signature_valid


def test_signature_validation() -> None:
    body = b'{"hello":"world"}'
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert signature_valid(body, signature, "secret")
    assert not signature_valid(body, signature, "wrong")


def test_only_admin_text_reaches_conversation() -> None:
    payload = {"entry": [{"changes": [{"value": {"messages": [{"from": "1555", "type": "text", "text": {"body": "approve it"}}, {"from": "999", "type": "text", "text": {"body": "ignore"}}]}}]}]}
    assert authorized_message(payload, "1555") == "approve it"
    assert authorized_message(payload, "000") is None
