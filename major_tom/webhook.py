"""Meta webhook. Message execution remains external and approval-gated."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, Header, HTTPException, Request

from major_tom.whatsapp import WhatsAppConfig, authorized_message, signature_valid


def create_app(on_message: Callable[[str], None] | None = None) -> FastAPI:
    """Create a verified, single-admin webhook application."""
    config = WhatsAppConfig.from_env()
    app = FastAPI(title="Major Tom", docs_url=None, redoc_url=None)

    @app.get("/webhook")
    def verify(hub_mode: str = "", hub_verify_token: str = "", hub_challenge: str = "") -> str:
        if hub_mode == "subscribe" and hmac_compare(hub_verify_token, config.verify_token):
            return hub_challenge
        raise HTTPException(status_code=403, detail="verification failed")

    @app.post("/webhook", status_code=200)
    async def receive(request: Request, x_hub_signature_256: str | None = Header(default=None)) -> dict[str, bool]:
        body = await request.body()
        if not signature_valid(body, x_hub_signature_256, config.app_secret):
            raise HTTPException(status_code=403, detail="invalid signature")
        text = authorized_message(await request.json(), config.admin_phone)
        if text and on_message:
            on_message(text)
        return {"ok": True}

    return app


def hmac_compare(left: str, right: str) -> bool:
    """Constant-time comparison for Meta subscription token."""
    import hmac

    return bool(right) and hmac.compare_digest(left, right)
