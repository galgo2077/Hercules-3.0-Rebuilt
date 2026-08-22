from __future__ import annotations

import os
import socket
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from SharedParams.Supabase import get_service_client


def _worker_id() -> str:
    return socket.gethostname() + ":" + str(os.getpid())


def acquire_lease(account_id: str, worker_id: str, ttl_seconds: int = 60) -> bool:
    db = get_service_client()
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()

    row = db.table("worker_leases").select("worker_id,expires_at").eq("account_id", account_id).maybe_single().execute()
    lease = row.data if row is not None else None
    if isinstance(lease, dict):
        expires_value = lease.get("expires_at")
        owner_value = lease.get("worker_id")
        if not isinstance(expires_value, str) or not isinstance(owner_value, str):
            raise ValueError(f"invalid lease record for {account_id}")
        existing_expires = datetime.fromisoformat(expires_value)
        if existing_expires.tzinfo is None:
            existing_expires = existing_expires.replace(tzinfo=timezone.utc)
        if existing_expires > now and owner_value != worker_id:
            return False
        db.table("worker_leases").update({"worker_id": worker_id, "expires_at": expires_at, "acquired_at": now.isoformat()}).eq("account_id", account_id).execute()
        return True

    db.table("worker_leases").insert(
        {"account_id": account_id, "worker_id": worker_id, "expires_at": expires_at, "acquired_at": now.isoformat()}
    ).execute()
    return True


def renew_lease(account_id: str, worker_id: str, ttl_seconds: int = 60) -> bool:
    db = get_service_client()
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
    result = db.table("worker_leases").update({"expires_at": expires_at}).eq("account_id", account_id).eq("worker_id", worker_id).execute()
    return bool(result.data)


def release_lease(account_id: str, worker_id: str) -> None:
    get_service_client().table("worker_leases").delete().eq("account_id", account_id).eq("worker_id", worker_id).execute()


def _engine_for(environment: str):
    """Return the correct engine class for the given environment string."""
    if environment == "real":
        from Live.Real import RealEngine
        return RealEngine
    from Live.Demo import DemoEngine
    return DemoEngine


@dataclass
class AccountWorker:
    account_id: str
    label: str = ""
    environment: str = "testnet"  # testnet | real
    worker_id: str = field(default_factory=_worker_id)

    _engine: object = field(default=None, init=False, repr=False)
    _engine_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _renew_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    def start(self) -> None:
        if not acquire_lease(self.account_id, self.worker_id):
            print(f"[Worker] lease held by another worker for {self.account_id}, abort")
            return

        from Live.Crypto import load_credential
        api_key, api_secret = load_credential(self.account_id)

        engine_cls = _engine_for(self.environment)
        label = self.label or self.account_id
        self._engine = engine_cls(api_key=api_key, api_secret=api_secret, label=label)

        self._stop_event.clear()
        self._engine_thread = threading.Thread(
            target=self._engine.start, daemon=True, name=f"engine-{label}"
        )
        self._engine_thread.start()

        self._renew_thread = threading.Thread(
            target=self._renew_loop, daemon=True, name=f"renew-{label}"
        )
        self._renew_thread.start()
        print(f"[Worker] started {label} ({self.environment}) worker_id={self.worker_id}")

    def stop(self) -> None:
        self._stop_event.set()
        if self._engine is not None:
            self._engine.stop()
        release_lease(self.account_id, self.worker_id)
        print(f"[Worker] stopped {self.label or self.account_id}")

    def _renew_loop(self) -> None:
        while not self._stop_event.wait(30):
            ok = renew_lease(self.account_id, self.worker_id)
            if not ok:
                print(f"[Worker] lease lost for {self.account_id}, stopping")
                self.stop()
                break
