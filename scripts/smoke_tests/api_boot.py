"""Smoke test — FastAPI surface boot path.

No LLM call. Constructs the app via the real lifespan (storage
initialised against a per-run tempdir SQLite) and hits `/health` to
prove the wiring works end-to-end.

What this validates:
  - api/app.py imports cleanly (no circular imports across api ↔
    orchestrator ↔ progress ↔ storage)
  - lifespan starts: Storage().initialise() succeeds against a fresh DB
  - CORS middleware mounts
  - GET /health returns 200 with the expected payload shape
  - lifespan shuts down cleanly (Storage.close() runs)
"""

from __future__ import annotations

import asyncio

from ._common import (
    SmokeResult,
    prepare_environment,
    run_smoke,
)

NAME = "api_boot"
REQUIRES_LIVE_LLM = False
ESTIMATED_COST_USD = 0.0


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()  # redirects sqlite_db_path + faiss_index_path

    messages: list[str] = []
    failures: list[str] = []

    try:
        from fastapi.testclient import TestClient

        from trajectory.api.app import create_app
    except Exception as exc:
        failures.append(f"import failed: {exc!r}")
        return messages, failures, 0.0

    try:
        app = create_app()
    except Exception as exc:
        failures.append(f"create_app() raised: {exc!r}")
        return messages, failures, 0.0

    # TestClient drives the lifespan via `with` — startup + shutdown
    # both run, exactly as uvicorn would.
    try:
        with TestClient(app) as client:
            messages.append("lifespan startup completed")

            resp = client.get("/health")
            if resp.status_code != 200:
                failures.append(
                    f"GET /health returned {resp.status_code} "
                    f"(body: {resp.text[:200]!r})"
                )
                return messages, failures, 0.0

            body = resp.json()
            messages.append(f"/health body: {body}")

            for required in ("status", "service", "version",
                             "storage_initialised",
                             "demo_user_id_configured"):
                if required not in body:
                    failures.append(f"/health missing field: {required}")

            if body.get("status") != "ok":
                failures.append(f"/health status was {body.get('status')!r}")

            if not body.get("storage_initialised"):
                failures.append("/health says storage_initialised=False")
    except Exception as exc:
        failures.append(f"TestClient flow raised: {exc!r}")
        return messages, failures, 0.0

    messages.append("lifespan shutdown completed cleanly")
    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
