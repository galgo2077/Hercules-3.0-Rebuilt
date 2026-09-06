"""Live entry point — load all active accounts from DB, start one worker per account."""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()


def _load_accounts() -> list[dict]:
    """Fetch all exchange_accounts rows from DB. Returns list of account dicts."""
    from SharedParams.Supabase import get_service_client

    resp = get_service_client().table("exchange_accounts").select("id,label,environment").execute()
    return [dict(row) for row in resp.data if isinstance(row, dict)] if isinstance(resp.data, list) else []


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
            account_id=str(acc["id"]),
            label=str(acc.get("label") or acc["id"]),
            environment=str(acc.get("environment") or "testnet"),
        )
        try:
            started = w.start()
        except Exception as exc:
            print(f"Failed to start account {w.label}: {exc}")
        else:
            if not started:
                continue
            workers.append(w)

    print(f"Started {len(workers)} account worker(s): {[w.label for w in workers]}")

    config = load()
    try:
        serve(config)  # blocks — uvicorn runs here
    finally:
        for worker in workers:
            worker.stop()


if __name__ == "__main__":
    main()
