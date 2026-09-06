from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from Live.Worker import AccountWorker, WorkerManager


class FakeWorker:
    leases: dict[str, str] = {}
    starts: list[str] = []
    stops: list[str] = []
    lock = threading.Lock()

    def __init__(self, account_id: str, label: str, environment: str, worker_id: str) -> None:
        self.account_id = account_id
        self.label = label
        self.environment = environment
        self.worker_id = worker_id
        self.running = False

    def start(self) -> bool:
        with self.lock:
            if self.account_id in self.leases:
                return False
            self.leases[self.account_id] = self.worker_id
            self.starts.append(self.account_id)
            self.running = True
            return True

    def stop(self) -> None:
        with self.lock:
            if self.leases.get(self.account_id) == self.worker_id:
                self.leases.pop(self.account_id)
            self.stops.append(self.account_id)
            self.running = False


def _reset_fake(monkeypatch) -> None:
    FakeWorker.leases = {}
    FakeWorker.starts = []
    FakeWorker.stops = []
    monkeypatch.setattr("Live.Worker.AccountWorker", FakeWorker)


def test_new_account_is_discovered_once(monkeypatch) -> None:
    _reset_fake(monkeypatch)
    accounts: list[dict] = []
    manager = WorkerManager(lambda: accounts)

    manager.reconcile()
    accounts.append({"id": "account-1", "label": "paper", "environment": "paper", "enabled": True})
    manager.reconcile()
    manager.reconcile()

    assert list(manager._workers) == ["account-1"]
    assert FakeWorker.starts == ["account-1"]
    manager.stop()


def test_concurrent_managers_use_one_lease_and_recover(monkeypatch) -> None:
    _reset_fake(monkeypatch)
    accounts = [{"id": "account-1", "label": "paper", "environment": "paper", "enabled": True}]
    managers = [WorkerManager(lambda: accounts), WorkerManager(lambda: accounts)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda manager: manager.reconcile(), managers))

    owners = [manager for manager in managers if manager._workers]
    assert len(owners) == 1
    assert FakeWorker.starts == ["account-1"]

    owner = owners[0]
    standby = managers[1] if managers[0] is owner else managers[0]
    owner.stop()
    standby.reconcile()
    assert list(standby._workers) == ["account-1"]
    assert FakeWorker.starts == ["account-1", "account-1"]
    standby.stop()


def test_disabled_and_deleted_accounts_stop(monkeypatch) -> None:
    _reset_fake(monkeypatch)
    account = {"id": "account-1", "label": "paper", "environment": "paper", "enabled": True}
    accounts = [account]
    manager = WorkerManager(lambda: accounts)

    manager.reconcile()
    account["enabled"] = False
    manager.reconcile()
    assert not manager._workers

    account["enabled"] = True
    manager.reconcile()
    accounts.clear()
    manager.reconcile()
    assert not manager._workers
    assert FakeWorker.stops == ["account-1", "account-1"]


def test_discovery_failure_preserves_worker(monkeypatch, capsys) -> None:
    _reset_fake(monkeypatch)
    fail = False

    def load_accounts() -> list[dict]:
        if fail:
            raise RuntimeError("sensitive database detail")
        return [{"id": "account-1", "label": "paper", "environment": "paper", "enabled": True}]

    manager = WorkerManager(load_accounts)
    manager.reconcile()
    fail = True
    manager.reconcile()

    assert list(manager._workers) == ["account-1"]
    output = capsys.readouterr().out
    assert "retaining current workers" in output
    assert "sensitive database detail" not in output
    manager.stop()


def test_shutdown_stops_discovery_and_workers(monkeypatch) -> None:
    _reset_fake(monkeypatch)
    account = {"id": "account-1", "label": "paper", "environment": "paper", "enabled": True}
    manager = WorkerManager(lambda: [account], interval_seconds=0.01)

    manager.start()
    thread = manager._thread
    manager.stop()

    assert thread is not None and not thread.is_alive()
    assert not manager._workers
    assert FakeWorker.stops == ["account-1"]


def test_account_worker_shutdown_joins_threads_and_releases_lease(monkeypatch) -> None:
    stopped = threading.Event()
    released: list[tuple[str, str]] = []

    class Engine:
        def __init__(self, **kwargs) -> None:
            pass

        def start(self) -> None:
            stopped.wait()

        def stop(self) -> None:
            stopped.set()

    monkeypatch.setattr("Live.Worker.acquire_lease", lambda account_id, worker_id: True)
    monkeypatch.setattr("Live.Worker.release_lease", lambda account_id, worker_id: released.append((account_id, worker_id)))
    monkeypatch.setattr("Live.Worker._engine_for", lambda environment: Engine)
    worker = AccountWorker("account-1", environment="paper", worker_id="worker-1")

    assert worker.start()
    worker.stop()

    assert worker._engine_thread is not None and not worker._engine_thread.is_alive()
    assert worker._renew_thread is not None and not worker._renew_thread.is_alive()
    assert released


def test_paper_stop_wakes_blocked_websocket(monkeypatch) -> None:
    import asyncio

    from Live.Paper import PaperEngine

    entered = threading.Event()

    class Socket:
        def __init__(self) -> None:
            self.closed = asyncio.Event()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def __aiter__(self):
            return self

        async def __anext__(self):
            entered.set()
            await self.closed.wait()
            raise StopAsyncIteration

        async def close(self) -> None:
            self.closed.set()

    engine = PaperEngine()
    monkeypatch.setattr(engine, "_warmup", lambda: None)
    monkeypatch.setattr("Live.Paper.websockets.connect", lambda url: Socket())
    thread = threading.Thread(target=engine.start)
    thread.start()
    assert entered.wait(timeout=2)

    engine.stop()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_demo_stop_closes_active_websocket() -> None:
    import asyncio

    from Live.Demo import DemoEngine

    async def verify() -> None:
        closed = asyncio.Event()

        class Socket:
            async def close(self) -> None:
                closed.set()

        engine = DemoEngine(api_key="key", api_secret="secret")
        engine._running = True
        engine._loop = asyncio.get_running_loop()
        engine._websocket = Socket()
        engine.stop()
        await asyncio.wait_for(closed.wait(), timeout=1)

    asyncio.run(verify())


def test_main_starts_and_stops_manager_around_server(monkeypatch) -> None:
    import Main

    events: list[str] = []

    class Manager:
        def __init__(self, load_accounts) -> None:
            assert load_accounts is Main._load_accounts

        def start(self) -> None:
            events.append("start")

        def stop(self) -> None:
            events.append("stop")

    monkeypatch.setattr("Live.Worker.WorkerManager", Manager)
    monkeypatch.setattr("SharedParams.Config.load", lambda: object())
    monkeypatch.setattr("Live.Server.main", lambda config: events.append("serve"))

    Main.main()
    assert events == ["start", "serve", "stop"]
