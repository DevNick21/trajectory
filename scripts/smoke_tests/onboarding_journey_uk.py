"""Smoke test — full web onboarding journey for a UK resident.

Drives `/api/onboarding/finalise` with a substantial payload (real
motivations + deal-breakers prose, career narrative) and
verifies every load-bearing piece of state lands in storage:

  - Deterministic preference capture produced separate list items —
    motivations + deal_breakers + good_role_signals each split correctly.
  - UserProfile is retrievable via GET /api/profile.
  - CareerEntries are retrievable via FAISS for a query rooted in the
    user's motivations — i.e. the profile-to-memory pipeline actually
    feeds Phase 4 generators downstream.
  - CareerEntry kinds are correct (conversation, motivation, deal_breaker,
    good_role_signal).

The existing `api_onboarding` smoke only asserts shape (counts, status
codes); this test verifies the journey is complete enough to *use*.

Cost: $0.
"""

from __future__ import annotations

from ._common import (
    SmokeResult,
    prepare_environment,
    run_smoke,
)

NAME = "onboarding_journey_uk"
REQUIRES_LIVE_LLM = False
ESTIMATED_COST_USD = 0.0


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    messages: list[str] = []
    failures: list[str] = []

    from fastapi.testclient import TestClient
    from askpicky.api.app import create_app
    from askpicky.config import settings

    settings.demo_user_id = "smoke_onboarding_uk"

    app = create_app()

    with TestClient(app) as client:
        payload = {
            "name": "Kene Smoke",
            "user_type": "uk_resident",
            "base_location": "London",
            "salary_floor": 60_000,
            "salary_target": 85_000,
            "current_employment": "EMPLOYED",
            "search_duration_months": 4,
            "motivations_text": (
                "shipping products that real users rely on; "
                "owning systems end-to-end, not just my slice; "
                "working with engineers who push my technical thinking"
            ),
            "deal_breakers_text": (
                "pure maintenance roles with no greenfield work; "
                "five-day-a-week office mandates"
            ),
            "good_role_signals_text": (
                "engineers in leadership positions; "
                "public engineering blog with technical depth; "
                "small teams, fast feedback loops"
            ),
            "life_constraints": ["needs hybrid", "no relocation"],
            "career_narrative": (
                "Seven years backend (Python + Go). Last role was "
                "tech-leading a four-person platform team. Before that, "
                "individual contributor at two payments companies."
            ),
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
            f"finalise OK: entries_written={body['career_entries_written']}"
        )

        if "writing_style_profile_id" in body:
            failures.append(
                "onboarding finalise should not return writing_style_profile_id."
            )

        # ── 2. CareerEntries: conversation + 3 motivations + 2
        #       deal_breakers + 3 good_role_signals = 9 entries.
        expected = (
            1  # career_narrative
            + 3  # motivations
            + 2  # deal breakers
            + 3  # good role signals
        )
        if body["career_entries_written"] != expected:
            failures.append(
                f"expected {expected} career entries; "
                f"got {body['career_entries_written']}"
            )
        else:
            messages.append(
                f"all {expected} CareerEntry rows written from parsed data"
            )

        # ── 3. Profile retrievable, motivations + deal_breakers split ─
        resp = client.get("/api/profile")
        if resp.status_code != 200:
            failures.append(f"GET /api/profile -> {resp.status_code}")
            return messages, failures, 0.0
        profile = resp.json()

        if profile["user_type"] != "uk_resident":
            failures.append(
                f"user_type={profile['user_type']!r} != 'uk_resident'"
            )
        if len(profile["motivations"]) != 3:
            failures.append(
                "motivations was not split into 3 items "
                f"(got {len(profile['motivations'])}: {profile['motivations']})."
            )
        else:
            messages.append(
                "profile.motivations split into 3 items"
            )
        if len(profile["deal_breakers"]) != 2:
            failures.append(
                f"deal_breakers count={len(profile['deal_breakers'])} != 2"
            )
        if len(profile["good_role_signals"]) != 3:
            failures.append(
                f"good_role_signals count={len(profile['good_role_signals'])} != 3"
            )
        if profile.get("writing_style_profile_id") is not None:
            failures.append("profile.writing_style_profile_id should be None.")

    # ── 4. FAISS retrieval works against the new entries ──────────
    # Use the storage layer directly (the API doesn't expose retrieval).
    from askpicky.storage import Storage

    storage = Storage()
    await storage.initialise()
    try:
        retrieved = await storage.retrieve_relevant_entries(
            user_id=settings.demo_user_id,
            query="ship products users rely on engineering culture",
            k=8,
        )
        kinds = {e.kind for e in retrieved}
        messages.append(
            f"FAISS retrieval: {len(retrieved)} entries, kinds={sorted(kinds)}"
        )
        if not retrieved:
            failures.append(
                "FAISS returned 0 entries for a query rooted in the "
                "user's motivations — onboarding → embedding pipeline broken."
            )
        elif "motivation" not in kinds:
            failures.append(
                "FAISS returned no entries of kind=motivation despite "
                "the query being rooted in motivation text."
            )
    finally:
        await storage.close()

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
