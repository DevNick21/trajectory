"""Smoke test — POST /api/onboarding/finalise (no LLM path).

Passes writing_samples=[] so the style extractor is skipped (no Opus
call). Empty free-text stages fall back to raw passthrough, so the
voice-stage parsers are also skipped. End result: a UserProfile + a
bundle of CareerEntry rows, zero LLM cost.

Cost: $0.
"""

from __future__ import annotations

import asyncio

from ._common import (
    SmokeResult,
    prepare_environment,
    run_smoke,
)

NAME = "api_onboarding"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from fastapi.testclient import TestClient
    from trajectory.config import settings
    from trajectory.api.app import create_app

    settings.demo_user_id = "smoke_onboarding_user"

    messages: list[str] = []
    failures: list[str] = []

    app = create_app()

    with TestClient(app) as client:
        payload = {
            "name": "Smoke Test",
            "user_type": "uk_resident",
            "base_location": "London",
            "salary_floor": 55_000,
            "salary_target": 75_000,
            "current_employment": "EMPLOYED",
            "search_duration_months": 3,
            "motivations_text": "Want to ship products that people use.",
            "deal_breakers_text": "No pure maintenance roles.",
            "good_role_signals_text": "Strong engineering culture.",
            "life_constraints": ["needs hybrid"],
            "writing_samples": [],   # <- skips Opus call
            "career_narrative": "Seven years of backend engineering.",
        }
        resp = client.post("/api/onboarding/finalise", json=payload)
        if resp.status_code != 201:
            failures.append(
                f"POST /api/onboarding/finalise -> {resp.status_code}: "
                f"{resp.text[:300]!r}"
            )
            return messages, failures, 0.0
        body = resp.json()
        messages.append(
            f"finalise OK: user_id={body['user_id']} "
            f"entries_written={body['career_entries_written']} "
            f"style_profile_id={body.get('writing_style_profile_id')}"
        )
        if body["career_entries_written"] < 3:
            failures.append(
                f"expected ≥ 3 career entries; got {body['career_entries_written']}"
            )
        if body.get("writing_style_profile_id") is not None:
            failures.append(
                "writing_style_profile_id should be None when samples are empty."
            )

        # Profile should now be retrievable.
        resp = client.get("/api/profile")
        if resp.status_code != 200:
            failures.append(f"GET /api/profile after finalise -> {resp.status_code}")
        else:
            p = resp.json()
            if p["user_id"] != settings.demo_user_id:
                failures.append(f"profile user_id mismatch: {p['user_id']}")
            else:
                messages.append(
                    f"GET /api/profile OK: motivations={len(p['motivations'])} "
                    f"deal_breakers={len(p['deal_breakers'])}"
                )

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    asyncio.run(run())
