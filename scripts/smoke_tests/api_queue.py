"""Smoke test — /api/queue CRUD (no LLM, no Phase 1).

Exercises POST + GET + DELETE. The SSE `/api/queue/process` endpoint is
NOT exercised here — it triggers real Phase 1 work (expensive). It has
its own dedicated e2e path.

Cost: $0.
"""

from __future__ import annotations

import asyncio

from ._common import (
    SmokeResult,
    build_test_user,
    prepare_environment,
    run_smoke,
)

NAME = "api_queue"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from fastapi.testclient import TestClient
    from trajectory.config import settings
    from trajectory.api.app import create_app

    settings.demo_user_id = "smoke_queue_user"
    # Keep rate limiter out of the way for smoke purposes.
    settings.enforce_rate_limit = False

    messages: list[str] = []
    failures: list[str] = []

    app = create_app()

    with TestClient(app) as client:
        user = build_test_user("uk_resident")
        user.user_id = settings.demo_user_id
        await app.state.storage.save_user_profile(user)

        # Empty payload is rejected.
        resp = client.post("/api/queue", json={})
        if resp.status_code != 400:
            failures.append(f"empty payload -> {resp.status_code} (expected 400)")

        # Add two URLs (with a duplicate to exercise dedup).
        resp = client.post(
            "/api/queue",
            json={"job_urls": [
                "https://example.com/jobs/a",
                "https://example.com/jobs/b",
                "https://example.com/jobs/a",
            ]},
        )
        if resp.status_code != 201:
            failures.append(
                f"POST /api/queue -> {resp.status_code}: {resp.text[:200]!r}"
            )
            return messages, failures, 0.0
        inserted = resp.json()
        if len(inserted) != 2:
            failures.append(
                f"insert dedup failed: expected 2, got {len(inserted)}"
            )
        else:
            messages.append(f"POST /api/queue OK: {len(inserted)} inserted")

        # List.
        resp = client.get("/api/queue")
        if resp.status_code != 200:
            failures.append(f"GET /api/queue -> {resp.status_code}")
        else:
            body = resp.json()
            if body.get("pending_count") != 2:
                failures.append(
                    f"pending_count={body.get('pending_count')} != 2"
                )
            else:
                messages.append(
                    f"GET /api/queue OK: {body['pending_count']} pending"
                )

        # Delete one.
        first_id = inserted[0]["id"]
        resp = client.delete(f"/api/queue/{first_id}")
        if resp.status_code != 204:
            failures.append(f"DELETE /api/queue/{first_id} -> {resp.status_code}")
        else:
            messages.append("DELETE /api/queue/{id} OK")

        # Deleting again is 404.
        resp = client.delete(f"/api/queue/{first_id}")
        if resp.status_code != 404:
            failures.append(f"double-delete -> {resp.status_code} (expected 404)")

        # Post-delete count is 1.
        resp = client.get("/api/queue")
        if resp.json().get("pending_count") != 1:
            failures.append(
                f"pending_count after delete = {resp.json().get('pending_count')} != 1"
            )

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    asyncio.run(run())
