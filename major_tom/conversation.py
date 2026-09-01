"""Safe hand-off entrypoint for messages accepted by the WhatsApp bridge."""

from __future__ import annotations

from .whatsapp_bridge import normalize_phone


def handle_message(text: str, sender: str) -> dict[str, str]:
    """Acknowledge one authorized bridge message without authorizing production changes."""
    message = text.strip()
    if not message or not normalize_phone(sender):
        return {"reply": "I could not read that message."}
    return {"reply": "Major Tom received your request. Investigation and read-only checks can run now; production changes and financial actions require a specific confirmation."}
