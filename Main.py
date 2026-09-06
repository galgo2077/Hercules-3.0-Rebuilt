"""Live entry point — reconcile active account workers while serving the API."""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()


def _load_accounts() -> list[dict]:
    """Fetch all exchange_accounts rows from DB. Returns list of account dicts."""
    from SharedParams.Supabase import get_service_client

    resp = get_service_client().table("exchange_accounts").select("id,label,environment,enabled").eq("enabled", True).execute()
    return [dict(row) for row in resp.data if isinstance(row, dict)] if isinstance(resp.data, list) else []


def main() -> None:
    from Live.Server import main as serve
    from Live.Worker import WorkerManager
    from SharedParams.Config import load

    workers = WorkerManager(_load_accounts)
    workers.start()
    config = load()
    try:
        serve(config)  # blocks — uvicorn runs here
    finally:
        workers.stop()


if __name__ == "__main__":
    main()
