"""Smoke test — /api/sessions/{id}/cv route wiring (no LLM via monkeypatch).

Validates the Phase 4 CV route without spending credits by monkey-
patching `orchestrator.handle_draft_cv` to return a synthetic output.
Asserts:
  - 404 when the session is unknown
  - 200 with the expected PackResult shape on success
  - 409 when no research bundle on the session

Set SMOKE_API_PACK_LIVE=1 to exercise the real Opus path (~$2).

Cost: $0 by default.
"""

from __future__ import annotations

import asyncio
import os

from ._common import (
    SmokeResult,
    build_synthetic_cv_output,
    build_test_session,
    build_test_user,
    prepare_environment,
    run_smoke,
)

NAME = "api_pack"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from fastapi.testclient import TestClient
    from trajectory.config import settings
    from trajectory.api.app import create_app

    settings.demo_user_id = "smoke_pack_user"
    settings.enforce_rate_limit = False

    messages: list[str] = []
    failures: list[str] = []

    live = os.getenv("SMOKE_API_PACK_LIVE", "").lower() in {"1", "true", "yes"}

    app = create_app()

    # Monkey-patch the orchestrator handler unless we explicitly want to
    # hit Opus. The pack endpoint lazily imports handle_draft_cv inside
    # the runner, so patch the symbol on the orchestrator module. Must
    # be restored in the `finally` below — otherwise the fake leaks
    # into later tests (notably phase4_cv which calls the real handler).
    original_handle_draft_cv = None
    if not live:
        from trajectory import orchestrator

        async def _fake_handle_draft_cv(session, user, storage):
            cv = build_synthetic_cv_output(name=user.name)
            # Mimic the real tuple: (cv, docx_path, pdf_path, ...)
            return cv, None, None, None

        original_handle_draft_cv = orchestrator.handle_draft_cv
        orchestrator.handle_draft_cv = _fake_handle_draft_cv
        messages.append("monkey-patched orchestrator.handle_draft_cv -> synthetic CV")

    try:
        with TestClient(app) as client:
            # 404 — unknown session id.
            resp = client.post("/api/sessions/nope/cv")
            if resp.status_code != 404:
                failures.append(
                    f"unknown session -> {resp.status_code} (expected 404)"
                )

            # Seed a user + a session with a (stubbed) phase1_output so
            # the endpoint doesn't 409 on the precondition.
            user = build_test_user("uk_resident")
            user.user_id = settings.demo_user_id
            session = build_test_session(user.user_id)
            session.phase1_output = {"extracted_jd": {"role_title": "SWE"}}
            await app.state.storage.save_user_profile(user)
            await app.state.storage.save_session(session)

            resp = client.post(f"/api/sessions/{session.session_id}/cv")
            if resp.status_code != 200:
                failures.append(
                    f"POST /api/sessions/{session.session_id[:8]}/cv -> "
                    f"{resp.status_code}: {resp.text[:300]!r}"
                )
            else:
                body = resp.json()
                if body.get("generator") != "cv":
                    failures.append(
                        f"generator field = {body.get('generator')!r}"
                    )
                if "output" not in body or "name" not in body["output"]:
                    failures.append(
                        f"PackResult missing output.name: {body}"
                    )
                else:
                    messages.append(
                        f"POST /cv OK: generator={body['generator']} "
                        f"output.name={body['output']['name']!r}"
                    )
    finally:
        # Restore the real orchestrator symbol so later smokes (notably
        # phase4_cv) see the unmonkey-patched handler. Without this, the
        # fake leaks into module state for the rest of the run_all.
        if original_handle_draft_cv is not None:
            from trajectory import orchestrator
            orchestrator.handle_draft_cv = original_handle_draft_cv

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    asyncio.run(run())
