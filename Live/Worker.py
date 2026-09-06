from __future__ import annotations

import os
import socket
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

from SharedParams.Supabase import get_service_client


class _Engine(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...


def _worker_id() -> str:
    return socket.gethostname() + ":" + str(os.getpid())


def acquire_lease(account_id: str, worker_id: str, ttl_seconds: int = 60) -> bool:
    db = get_service_client()
    result = db.rpc(
        "acquire_worker_lease",
        {
            "p_account_id": account_id,
            "p_worker_id": worker_id,
            "p_ttl_seconds": ttl_seconds,
        },
    ).execute()
    return result.data is True or result.data == [True]


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
    environment = environment.lower()
    if environment == "real":
        from Live.Real import RealEngine

        return RealEngine
    if environment == "paper":
        from Live.Paper import PaperEngine

        return PaperEngine
    if environment in {"demo", "testnet"}:
        from Live.Demo import DemoEngine

        return DemoEngine
    raise ValueError(f"unsupported worker environment: {environment}")


@dataclass
class AccountWorker:
    account_id: str
    label: str = ""
    environment: str = "testnet"
    worker_id: str = field(default_factory=_worker_id)

    _engine: _Engine | None = field(default=None, init=False, repr=False)
    _engine_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _renew_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _lease_held: bool = field(default=False, init=False, repr=False)

    def start(self) -> bool:
        if not acquire_lease(self.account_id, self.worker_id):
            print(f"[Worker] lease held by another worker for {self.account_id}, abort")
            return False

        self._lease_held = True
        try:
            engine_cls = _engine_for(self.environment)
            label = self.label or self.account_id
            if self.environment.lower() == "paper":
                kwargs = {}
            else:
                from Live.Crypto import load_credential

                api_key, api_secret = load_credential(self.account_id)
                kwargs = {"api_key": api_key, "api_secret": api_secret, "label": label}
            self._engine = engine_cls(**kwargs)
        except Exception:
            release_lease(self.account_id, self.worker_id)
            self._lease_held = False
            raise

        self._stop_event.clear()
        self._engine_thread = threading.Thread(target=self._run_engine, daemon=True, name=f"engine-{label}")
        self._engine_thread.start()

        self._renew_thread = threading.Thread(target=self._renew_loop, daemon=True, name=f"renew-{label}")
        self._renew_thread.start()
        print(f"[Worker] started {label} ({self.environment}) worker_id={self.worker_id}")
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._engine is not None:
            self._engine.stop()
        self._release_lease()
        print(f"[Worker] stopped {self.label or self.account_id}")

    def _release_lease(self) -> None:
        if self._lease_held:
            release_lease(self.account_id, self.worker_id)
            self._lease_held = False

    def _run_engine(self) -> None:
        if self._engine is None:
            return
        try:
            self._engine.start()
        finally:
            self._stop_event.set()
            self._release_lease()

    def _renew_loop(self) -> None:
        while not self._stop_event.wait(30):
            ok = renew_lease(self.account_id, self.worker_id)
            if not ok:
                print(f"[Worker] lease lost for {self.account_id}, stopping")
                self._stop_event.set()
                if self._engine is not None:
                    self._engine.stop()
                break
