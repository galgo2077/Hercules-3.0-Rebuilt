from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

_IMAGE = "docker.io/library/postgres:17-alpine"
_PODMAN = shutil.which("podman")


def _run(*args: str, input: str | None = None) -> str:
    return subprocess.run(args, input=input, text=True, check=True, capture_output=True).stdout.strip()  # noqa: S603 - fixed test commands


def _psql(container: str, sql: str) -> str:
    assert _PODMAN is not None
    return _run(_PODMAN, "exec", "-i", container, "psql", "-v", "ON_ERROR_STOP=1", "-At", "-U", "postgres", input=sql)


def test_schema_reruns_and_lease_acquisition_is_atomic() -> None:
    if _PODMAN is None or subprocess.run([_PODMAN, "image", "exists", _IMAGE], check=False).returncode:  # noqa: S603 - fixed test command
        pytest.skip(f"requires cached {_IMAGE} and podman")

    container = f"hercules-schema-{uuid.uuid4().hex[:12]}"
    _run(_PODMAN, "run", "-d", "--rm", "--name", container, "-e", "POSTGRES_PASSWORD=local-validation", _IMAGE)
    try:
        for _ in range(30):
            if subprocess.run([_PODMAN, "exec", container, "pg_isready", "-U", "postgres"], check=False, capture_output=True).returncode == 0:  # noqa: S603 - fixed test command
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("temporary PostgreSQL did not start")

        _psql(
            container,
            "CREATE SCHEMA auth; CREATE TABLE auth.users(id UUID PRIMARY KEY); "
            "CREATE FUNCTION auth.uid() RETURNS UUID LANGUAGE sql STABLE AS "
            "'SELECT nullif(current_setting(''request.jwt.claim.sub'', true), '''')::uuid'; "
            "CREATE ROLE service_role NOLOGIN;",
        )
        schema = (Path(__file__).resolve().parents[1] / "Storage" / "schema.sql").read_text(encoding="utf-8")
        _psql(container, schema)
        _psql(container, schema)
        _psql(
            container,
            "INSERT INTO auth.users VALUES ('00000000-0000-0000-0000-000000000001'); "
            "INSERT INTO exchange_accounts(user_id,label,api_key,key_meta,api_secret,secret_meta,environment) "
            "VALUES ('00000000-0000-0000-0000-000000000001','paper-regression','',':','',':','paper');",
        )
        query = "SELECT acquire_worker_lease(id, $1, 60) FROM exchange_accounts WHERE label='paper-regression'"

        def acquire(worker: str) -> str:
            return _psql(container, query.replace("$1", f"'{worker}'"))

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(acquire, ("worker-a", "worker-b")))
        assert sorted(results) == ["f", "t"]
        owner = _psql(container, "SELECT worker_id FROM worker_leases")
        standby = "worker-b" if owner == "worker-a" else "worker-a"
        assert acquire(owner) == "t"
        assert acquire(standby) == "f"
        _psql(container, "UPDATE worker_leases SET expires_at = now() - interval '1 second'")
        assert acquire(standby) == "t"
    finally:
        subprocess.run([_PODMAN, "stop", "-t", "0", container], check=False, capture_output=True)  # noqa: S603 - fixed test command
