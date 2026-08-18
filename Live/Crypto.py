"""AES-GCM credential encryption — Binance API keys encrypted at rest in Supabase."""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_LEN = 32  # 256-bit
_NONCE_LEN = 12  # 96-bit GCM nonce


def _master_key() -> bytes:
    raw = os.environ["HERCULES_MASTER_KEY"]
    key = base64.b64decode(raw)
    if len(key) != _KEY_LEN:
        raise ValueError(f"HERCULES_MASTER_KEY must be 32 bytes (got {len(key)})")
    return key


def generate_key() -> str:
    """Generate a new base64-encoded 256-bit key for HERCULES_MASTER_KEY."""
    return base64.b64encode(os.urandom(_KEY_LEN)).decode()


def encrypt(plaintext: str) -> dict[str, str]:
    """Encrypt plaintext with AES-256-GCM. Returns base64-encoded fields."""
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(_master_key()).encrypt(nonce, plaintext.encode(), None)
    # last 16 bytes of ct are the GCM tag
    return {
        "ciphertext": base64.b64encode(ct[:-16]).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "tag": base64.b64encode(ct[-16:]).decode(),
    }


def decrypt(ciphertext: str, nonce: str, tag: str) -> str:
    """Decrypt AES-256-GCM ciphertext. Returns plaintext string."""
    ct = base64.b64decode(ciphertext) + base64.b64decode(tag)
    n = base64.b64decode(nonce)
    return AESGCM(_master_key()).decrypt(n, ct, None).decode()


def store_credential(
    account_id: str, api_key: str, api_secret: str
) -> None:
    """Encrypt and upsert Binance credentials into Supabase exchange_accounts."""
    from SharedParams.Supabase import get_service_client

    enc_key = encrypt(api_key)
    enc_secret = encrypt(api_secret)
    get_service_client().table("exchange_accounts").update({
        "api_key": enc_key["ciphertext"],
        "api_secret": enc_secret["ciphertext"],
        # store nonce+tag alongside: pack as "nonce:tag" in separate json column
        "key_meta": f"{enc_key['nonce']}:{enc_key['tag']}",
        "secret_meta": f"{enc_secret['nonce']}:{enc_secret['tag']}",
    }).eq("id", account_id).execute()


def load_credential(account_id: str) -> tuple[str, str]:
    """Fetch and decrypt Binance API key + secret from Supabase."""
    from SharedParams.Supabase import get_service_client

    row = (
        get_service_client()
        .table("exchange_accounts")
        .select("api_key,api_secret,key_meta,secret_meta")
        .eq("id", account_id)
        .single()
        .execute()
        .data
    )
    key_nonce, key_tag = row["key_meta"].split(":")
    sec_nonce, sec_tag = row["secret_meta"].split(":")
    api_key = decrypt(row["api_key"], key_nonce, key_tag)
    api_secret = decrypt(row["api_secret"], sec_nonce, sec_tag)
    return api_key, api_secret
