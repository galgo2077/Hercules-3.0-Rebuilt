from __future__ import annotations

import os
import socket
import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable, Protocol

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
    return acquire_lease(account_id, worker_id, ttl_seconds)


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

    @property
    def running(self) -> bool:
        return self._lease_held and self._engine_thread is not None and self._engine_thread.is_alive()

    def start(self) -> bool:
        if not acquire_lease(self.account_id, self.worker_id):
            print(f"[Worker] lease held by another worker for {self.account_id}, abort")
            return False

        self._lease_held = True
        try:
            engine_cls = _engine_for(self.environment)
            label = self.label or self.account_id
            if self.environment.lower() == "paper":
                kwargs = {"account_id": self.account_id}
            else:
                from Live.Crypto import load_credential

                api_key, api_secret = load_credential(self.account_id)
                kwargs = {"api_key": api_key, "api_secret": api_secret, "label": label, "account_id": self.account_id}
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
        current = threading.current_thread()
        for thread in (self._renew_thread, self._engine_thread):
            if thread is not None and thread is not current:
                thread.join(timeout=5)
        print(f"[Worker] stopped {self.label or self.account_id}")

    def _release_lease(self) -> None:
        if self._lease_held:
            try:
                release_lease(self.account_id, self.worker_id)
            except Exception:
                print("[Worker] lease release failed; it will expire")
            finally:
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
            try:
                ok = renew_lease(self.account_id, self.worker_id)
            except Exception:
                print("[Worker] lease renewal failed; stopping")
                ok = False
            if not ok:
                print(f"[Worker] lease lost for {self.account_id}, stopping")
                self._stop_event.set()
                if self._engine is not None:
                    self._engine.stop()
                break


class WorkerManager:
    """Reconcile enabled accounts while serving: one lease, one worker, no restart."""

    def __init__(self, load_accounts: Callable[[], list[dict]], interval_seconds: float = 10) -> None:
        self._load_accounts = load_accounts
        self._interval_seconds = interval_seconds
        self._worker_id = f"{_worker_id()}:{uuid.uuid4().hex}"
        self._workers: dict[str, AccountWorker] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self.reconcile()
        self._thread = threading.Thread(target=self._run, daemon=True, name="account-discovery")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join()
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.stop()

    def reconcile(self) -> None:
        try:
            accounts = self._load_accounts()
        except Exception:
            print("[Worker] account discovery failed; retaining current workers")
            return

        desired = {str(account["id"]): account for account in accounts if account.get("id") and account.get("enabled", True) is True}
        with self._lock:
            for account_id, worker in list(self._workers.items()):
                account = desired.get(account_id)
                environment = str(account.get("environment") or "testnet") if account else ""
                if account is None or worker.environment != environment or not worker.running:
                    self._workers.pop(account_id)
                    worker.stop()

            for account_id, account in desired.items():
                if account_id in self._workers:
                    continue
                worker = AccountWorker(
                    account_id=account_id,
                    label=str(account.get("label") or account_id),
                    environment=str(account.get("environment") or "testnet"),
                    worker_id=self._worker_id,
                )
                try:
                    if worker.start():
                        self._workers[account_id] = worker
                except Exception:
                    print("[Worker] discovered account failed to start")

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            self.reconcile()
