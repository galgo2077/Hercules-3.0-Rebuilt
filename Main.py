"""Live entry point — load all active accounts from DB, start one worker per account."""

from __future__ import annotations

import signal
import time

from dotenv import load_dotenv

load_dotenv()


def _load_accounts() -> list[dict]:
    """Fetch all exchange_accounts rows from DB. Returns list of account dicts."""
    from SharedParams.Supabase import get_service_client
    resp = get_service_client().table("exchange_accounts").select("id,label,environment").execute()
    return resp.data if isinstance(resp.data, list) else []


def main() -> None:
    from Live.Server import main as serve
    from Live.Worker import AccountWorker
    from SharedParams.Config import load

    accounts = _load_accounts()
    if not accounts:
        print("No exchange accounts found in DB — add accounts via POST /api/accounts")

    workers: list[AccountWorker] = []
    for acc in accounts:
        w = AccountWorker(
            account_id=acc["id"],
            label=acc.get("label", acc["id"]),
            environment=acc.get("environment", "testnet"),
        )
        w.start()
        workers.append(w)

    print(f"Started {len(workers)} account worker(s): {[w.label for w in workers]}")

    def _shutdown(sig, frame):  # noqa: ANN001
        print("\nShutting down workers...")
        for w in workers:
            w.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    config = load()
    serve(config)  # blocks — uvicorn runs here


if __name__ == "__main__":
    main()
