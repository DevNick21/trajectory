"""Smoke test — GET /api/sessions + GET /api/sessions/{id} (no LLM).

Seeds a session, then:
  - GET /api/sessions — list returns the seeded row
  - GET /api/sessions/{id} — detail payload shape
  - GET /api/sessions/other_id — 404

Cost: $0.
"""

from __future__ import annotations

import asyncio

from ._common import (
    SmokeResult,
    build_test_session,
    build_test_user,
    prepare_environment,
    run_smoke,
)

NAME = "api_sessions"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from fastapi.testclient import TestClient
    from trajectory.config import settings
    from trajectory.api.app import create_app

    settings.demo_user_id = "smoke_sessions_user"

    messages: list[str] = []
    failures: list[str] = []

    app = create_app()

    with TestClient(app) as client:
        user = build_test_user("uk_resident")
        user.user_id = settings.demo_user_id
        session = build_test_session(user.user_id)

        await app.state.storage.save_user_profile(user)
        await app.state.storage.save_session(session)

        # List
        resp = client.get("/api/sessions")
        if resp.status_code != 200:
            failures.append(f"GET /api/sessions -> {resp.status_code}")
        else:
            body = resp.json()
            ids = [s["id"] for s in body.get("sessions", [])]
            if session.session_id not in ids:
                failures.append(
                    f"seeded session {session.session_id} missing from list; got {ids}"
                )
            else:
                messages.append(f"GET /api/sessions OK: {len(ids)} row(s)")

        # Detail
        resp = client.get(f"/api/sessions/{session.session_id}")
        if resp.status_code != 200:
            failures.append(
                f"GET /api/sessions/{session.session_id} -> {resp.status_code}: "
                f"{resp.text[:200]!r}"
            )
        else:
            body = resp.json()
            for field in ("id", "user_id", "intent", "created_at", "cost_summary"):
                if field not in body:
                    failures.append(f"detail missing field {field!r}")
            messages.append(
                f"GET /api/sessions/{session.session_id[:8]}... OK"
            )

        # 404 for a session that doesn't exist.
        resp = client.get("/api/sessions/does-not-exist")
        if resp.status_code != 404:
            failures.append(f"404 branch returned {resp.status_code}")
        else:
            messages.append("404 on unknown session id OK")

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    asyncio.run(run())
