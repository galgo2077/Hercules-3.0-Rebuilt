#!/usr/bin/env python3
"""One-time setup — store Binance credentials (testnet + real) encrypted in Supabase.

Run once before any live/field-test execution:
    source .venv/bin/activate
    export SUPABASE_URL=...
    export SUPABASE_SERVICE_ROLE_KEY=...
    export HERCULES_MASTER_KEY=...    # D28DFBj7K4FjkfFj4bP/3JXSGTKbHDWrpOFbpVbw1ZA=
    python setup_demo_account.py

Creates (or updates) rows in exchange_accounts for environment='testnet' and environment='real'.
Credentials are AES-256-GCM encrypted before writing — plaintext never touches the DB.
"""

from __future__ import annotations

import getpass
import os
import sys
import uuid

# ── env check ─────────────────────────────────────────────────────────────────

_REQUIRED = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "HERCULES_MASTER_KEY")
_missing = [v for v in _REQUIRED if not os.environ.get(v)]
if _missing:
    print(f"ERROR: missing env vars: {', '.join(_missing)}")
    print("Set them before running this script.")
    sys.exit(1)

# ── imports after env check ────────────────────────────────────────────────────

from Live.Crypto import encrypt  # noqa: E402 - requires successful environment validation
from SharedParams.Supabase import get_service_client  # noqa: E402 - requires successful environment validation


def _get_or_create_user() -> str:
    """Return a Supabase auth user UUID. Creates one if none exist."""
    db = get_service_client()
    try:
        resp = db.auth.admin.list_users()
        users = resp if isinstance(resp, list) else getattr(resp, "users", [])
        if users:
            uid = users[0].id
            print(f"  Using existing auth user: {uid}")
            return str(uid)
    except Exception as exc:
        print(f"  Warning: could not list auth users ({exc})")

    # Create a service/system user for the trading engine
    email = "trading@hercules.local"
    password = str(uuid.uuid4())  # random password — engine never logs in via password
    try:
        resp = db.auth.admin.create_user({"email": email, "password": password, "email_confirm": True})
        user = resp.user if hasattr(resp, "user") else resp
        uid = str(user.id)
        print(f"  Created auth user: {email}  id={uid}")
        return uid
    except Exception as exc:
        # User may already exist with that email
        if "already" in str(exc).lower():
            resp2 = db.auth.admin.list_users()
            users2 = resp2 if isinstance(resp2, list) else getattr(resp2, "users", [])
            match = next((u for u in users2 if getattr(u, "email", "") == email), None)
            if match:
                uid = str(match.id)
                print(f"  Reusing existing system user: {email}  id={uid}")
                return uid
        print(f"ERROR: cannot create auth user: {exc}")
        sys.exit(1)


def _upsert_account(user_id: str, label: str, environment: str, api_key: str, api_secret: str) -> str:
    """Upsert an exchange_accounts row. Returns the account UUID."""
    db = get_service_client()

    enc_key = encrypt(api_key)
    enc_secret = encrypt(api_secret)

    payload = {
        "user_id": user_id,
        "label": label,
        "environment": environment,
        "api_key": enc_key["ciphertext"],
        "key_meta": f"{enc_key['nonce']}:{enc_key['tag']}",
        "api_secret": enc_secret["ciphertext"],
        "secret_meta": f"{enc_secret['nonce']}:{enc_secret['tag']}",
    }

    # Check if row already exists (same user_id + label = unique constraint)
    existing = db.table("exchange_accounts").select("id").eq("user_id", user_id).eq("label", label).execute()
    rows = existing.data or []

    if rows:
        account_id = rows[0]["id"]
        db.table("exchange_accounts").update({
            k: v for k, v in payload.items() if k not in ("user_id", "label", "environment")
        }).eq("id", account_id).execute()
        print(f"  Updated {environment} ({label})  id={account_id}")
    else:
        result = db.table("exchange_accounts").insert(payload).execute()
        account_id = result.data[0]["id"]
        print(f"  Created {environment} ({label})  id={account_id}")

    return account_id


def _prompt_creds(label: str) -> tuple[str, str]:
    print(f"\n  Enter Binance {label} credentials (input hidden):")
    api_key = getpass.getpass(f"    API Key  [{label}]: ").strip()
    api_secret = getpass.getpass(f"    Secret   [{label}]: ").strip()
    if not api_key or not api_secret:
        print("  ERROR: API key and secret cannot be empty")
        sys.exit(1)
    return api_key, api_secret


def main() -> None:
    print("\n═══ Hercules credential setup ═══\n")

    # 1. Auth user
    print("── Auth user")
    user_id = _get_or_create_user()

    # 2. Testnet
    print("\n── Testnet (Binance USDT-M Futures testnet)")
    print("  https://testnet.binancefuture.com — register at https://testnet.binancefuture.com/en/futures/ref/")
    testnet_key, testnet_secret = _prompt_creds("testnet")
    testnet_id = _upsert_account(user_id, "binance-testnet", "testnet", testnet_key, testnet_secret)

    # 3. Real
    print("\n── Real (Binance USDT-M Futures production)")
    print("  WARNING: real account — actual funds. Only set if ready for live trading.")
    do_real = input("  Store real account credentials? [y/N]: ").strip().lower()
    real_id: str | None = None
    if do_real == "y":
        real_key, real_secret = _prompt_creds("real")
        real_id = _upsert_account(user_id, "binance-real", "real", real_key, real_secret)

    # 4. Verify round-trip decrypt
    print("\n── Verify decrypt")
    try:
        from Live.Crypto import load_credential
        k, s = load_credential(testnet_id)
        if k == testnet_key and s == testnet_secret:
            print("  [PASS] Testnet decrypt round-trip correct")
        else:
            print("  [FAIL] Testnet decrypt mismatch — credentials corrupted!")
            sys.exit(1)
        if real_id:
            from Live.Crypto import load_credential as lc
            rk, rs = lc(real_id)
            if rk == real_key and rs == real_secret:
                print("  [PASS] Real decrypt round-trip correct")
            else:
                print("  [FAIL] Real decrypt mismatch — credentials corrupted!")
                sys.exit(1)
    except Exception as exc:
        print(f"  [FAIL] Decrypt error: {exc}")
        sys.exit(1)

    # 5. Summary
    print("\n═══ Done ═══\n")
    print(f"  user_id     : {user_id}")
    print(f"  testnet id  : {testnet_id}")
    if real_id:
        print(f"  real id     : {real_id}")
    print()
    print("  Run field test:")
    print("    python field_test_orders.py")
    print()


if __name__ == "__main__":
    main()
