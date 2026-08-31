"""Small Meta WhatsApp Cloud API boundary."""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

import httpx


@dataclass(frozen=True, slots=True)
class WhatsAppConfig:
    admin_phone: str
    verify_token: str
    app_secret: str
    access_token: str
    phone_number_id: str

    @classmethod
    def from_env(cls) -> "WhatsAppConfig":
        return cls(
            admin_phone=os.environ.get("MAJOR_TOM_ADMIN_PHONE", ""),
            verify_token=os.environ.get("WHATSAPP_VERIFY_TOKEN", ""),
            app_secret=os.environ.get("WHATSAPP_APP_SECRET", ""),
            access_token=os.environ.get("WHATSAPP_ACCESS_TOKEN", ""),
            phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
        )

    @property
    def enabled(self) -> bool:
        return all((self.admin_phone, self.verify_token, self.app_secret, self.access_token, self.phone_number_id))


def signature_valid(body: bytes, signature: str | None, app_secret: str) -> bool:
    """Validate Meta X-Hub-Signature-256 before parsing untrusted input."""
    if not app_secret or not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


def authorized_message(payload: dict, admin_phone: str) -> str | None:
    """Return one authorized text message. Ignore all other senders/types."""
    if not admin_phone:
        return None
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for message in change.get("value", {}).get("messages", []):
                if message.get("from") == admin_phone and message.get("type") == "text":
                    return str(message.get("text", {}).get("body", "")).strip() or None
    return None


def send_text(config: WhatsAppConfig, message: str) -> None:
    """Send alert only after complete secret configuration exists."""
    if not config.enabled:
        raise RuntimeError("WhatsApp is not configured")
    url = f"https://graph.facebook.com/v21.0/{config.phone_number_id}/messages"
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {config.access_token}"},
        json={"messaging_product": "whatsapp", "to": config.admin_phone, "type": "text", "text": {"body": message}},
        timeout=15,
    )
    response.raise_for_status()
