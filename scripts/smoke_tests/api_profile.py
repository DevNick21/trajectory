"""Smoke test — GET /api/profile (FastAPI TestClient, no LLM).

Seeds a UserProfile via app.state.storage after lifespan startup,
then hits the endpoint. Verifies the 404 branch when no profile
exists too.

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

NAME = "api_profile"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from fastapi.testclient import TestClient
    from trajectory.config import settings
    from trajectory.api.app import create_app

    settings.demo_user_id = "smoke_api_user"

    messages: list[str] = []
    failures: list[str] = []

    app = create_app()

    with TestClient(app) as client:
        # 404 when no profile is seeded.
        resp = client.get("/api/profile")
        if resp.status_code != 404:
            failures.append(
                f"GET /api/profile with no profile returned {resp.status_code}; "
                "expected 404."
            )
        else:
            messages.append("404 on missing profile OK")

        # Seed the profile via the lifespan-created Storage. TestClient is
        # synchronous — our _body is async but TestClient's context manager
        # blocks the loop during HTTP calls, so the storage module's
        # aiosqlite connections are free to be awaited directly here.
        user = build_test_user("uk_resident")
        user.user_id = settings.demo_user_id
        await app.state.storage.save_user_profile(user)

        resp = client.get("/api/profile")
        if resp.status_code != 200:
            failures.append(
                f"GET /api/profile after seeding returned {resp.status_code}: "
                f"{resp.text[:200]!r}"
            )
        else:
            body = resp.json()
            if body.get("user_id") != settings.demo_user_id:
                failures.append(
                    f"returned user_id={body.get('user_id')!r} != {settings.demo_user_id!r}"
                )
            else:
                messages.append(
                    f"GET /api/profile OK: user_id={body['user_id']} "
                    f"user_type={body.get('user_type')}"
                )

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    asyncio.run(run())
