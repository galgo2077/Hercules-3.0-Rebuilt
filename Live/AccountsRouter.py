"""Exchange accounts CRUD API — list, add, delete Binance API credentials."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from Live.Auth import AuthUser, require_auth

router = APIRouter(prefix="/api/accounts", tags=["accounts"])
_User = Annotated[AuthUser, Depends(require_auth)]


def _records(data: object) -> list[dict]:
    return [dict(row) for row in data if isinstance(row, dict)] if isinstance(data, list) else []


class AddAccountRequest(BaseModel):
    label: str
    api_key: str
    api_secret: str
    environment: str = "testnet"  # testnet | real


@router.get("")
async def list_accounts(user: _User) -> list[dict]:
    from SharedParams.Supabase import get_service_client

    resp = get_service_client().table("exchange_accounts").select("id,label,environment,created_at").eq("user_id", user.id).order("created_at", desc=True).execute()
    return _records(resp.data)


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_account(body: AddAccountRequest, user: _User) -> dict:
    from Live.Crypto import encrypt
    from SharedParams.Supabase import get_service_client

    enc_key = encrypt(body.api_key)
    enc_sec = encrypt(body.api_secret)

    resp = (
        get_service_client()
        .table("exchange_accounts")
        .insert(
            {
                "user_id": user.id,
                "label": body.label,
                "environment": body.environment,
                "api_key": enc_key["ciphertext"],
                "api_secret": enc_sec["ciphertext"],
                "key_meta": f"{enc_key['nonce']}:{enc_key['tag']}",
                "secret_meta": f"{enc_sec['nonce']}:{enc_sec['tag']}",
            }
        )
        .execute()
    )
    rows = _records(resp.data)
    if not rows:
        raise HTTPException(status_code=500, detail="insert failed")
    return rows[0]


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(account_id: str, user: _User) -> None:
    from SharedParams.Supabase import get_service_client

    existing = get_service_client().table("exchange_accounts").select("id").eq("id", account_id).eq("user_id", user.id).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="not found")
    get_service_client().table("exchange_accounts").delete().eq("id", account_id).execute()
