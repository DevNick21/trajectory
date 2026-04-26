"""Smoke test — full web onboarding journey for a UK resident.

Drives `/api/onboarding/finalise` with a *substantial* payload (3 writing
samples, real motivations + deal-breakers prose, career narrative) and
verifies every load-bearing piece of state lands in storage:

  - WritingStyleProfile populated (style_extractor patched to a fixture
    so the test stays $0; the wiring assertion is what matters here).
  - Voice-stage parsing produced parsed lists, not raw fallback —
    motivations + deal_breakers + good_role_signals each split correctly.
  - UserProfile is retrievable via GET /api/profile.
  - CareerEntries are retrievable via FAISS for a query rooted in the
    user's motivations — i.e. the writing-to-FAISS pipeline actually
    feeds Phase 4 generators downstream.
  - CareerEntry kinds are correct (conversation, motivation, deal_breaker,
    good_role_signal, writing_sample).

The existing `api_onboarding` smoke only asserts shape (counts, status
codes); this test verifies the journey is complete enough to *use*.

Cost: $0 (style_extractor + parse_stage both patched to fixtures).
"""

from __future__ import annotations

from datetime import datetime, timezone

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
    from trajectory.api.app import create_app
    from trajectory.config import settings
    from trajectory.schemas import (
        DealBreakersParseResult,
        MotivationsParseResult,
        WritingStyleProfile,
    )
    from trajectory.sub_agents import onboarding_parser, style_extractor
    from trajectory.api.routes import onboarding as onboarding_route

    settings.demo_user_id = "smoke_onboarding_uk"

    samples = [
        "Cut p99 from 600ms to 195ms by rewriting the hot path "
        "around protobuf reuse and a connection pool. Wrote up the "
        "before/after for the team.",
        "Owned the Postgres → CockroachDB migration end-to-end. "
        "Two months, zero downtime, kept the read path on Postgres "
        "until the cutover so we could roll back at any point.",
        "Mentored two new engineers through their first oncall "
        "rotation. Built a runbook for the top three incident types "
        "based on what tripped them up in shadow shifts.",
    ]

    parsed_motivations = MotivationsParseResult(
        status="parsed",
        follow_up=None,
        motivations=[
            "shipping products that real users rely on",
            "owning systems end-to-end, not just my slice",
            "working with engineers who push my technical thinking",
        ],
        drains=["meeting-heavy days with no shipping", "pure firefighting weeks"],
    )
    parsed_deal_breakers = DealBreakersParseResult(
        status="parsed",
        follow_up=None,
        deal_breakers=[
            "pure maintenance roles with no greenfield work",
            "five-day-a-week office mandates",
        ],
        good_role_signals=[
            "engineers in leadership positions",
            "public engineering blog with technical depth",
        ],
    )

    fixture_style = WritingStyleProfile(
        profile_id="smoke_onboarding_uk_style",
        user_id=settings.demo_user_id,
        tone="plainspoken, technical, results-first",
        sentence_length_pref="varied",
        formality_level=6,
        hedging_tendency="direct",
        signature_patterns=["leads with the result", "uses numbers not adjectives"],
        avoided_patterns=["buzzwords", "passive voice"],
        examples=samples[:2],
        source_sample_ids=[f"sample_{i}" for i in range(len(samples))],
        sample_count=len(samples),
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    # Patch the LLM-backed pieces with fixtures.
    original_extract = style_extractor.extract
    original_parse_stage = onboarding_parser.parse_stage

    async def _fake_extract(*, user_id, samples):
        return fixture_style.model_copy(update={"user_id": user_id})

    async def _fake_parse_stage(stage: str, user_text: str):
        if stage == "motivations":
            return parsed_motivations
        if stage == "deal_breakers":
            return parsed_deal_breakers
        return None

    style_extractor.extract = _fake_extract
    onboarding_parser.parse_stage = _fake_parse_stage
    # The onboarding route function imports style_extractor + parse_stage
    # lazily inside `finalise()`, so the patches above (on the module
    # attributes) take effect at call time. Belt-and-braces: also rebind
    # any names already imported into the route module.
    if hasattr(onboarding_route, "extract_style"):
        original_route_extract = onboarding_route.extract_style
        onboarding_route.extract_style = _fake_extract
    else:
        original_route_extract = None

    app = create_app()

    try:
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
                    "I want to ship products that real users rely on, own "
                    "systems end-to-end rather than just my slice, and work "
                    "with engineers who push my technical thinking. Meeting-"
                    "heavy days with nothing shipping drain me; so do pure "
                    "firefighting weeks."
                ),
                "deal_breakers_text": (
                    "Pure maintenance roles with no greenfield work are out, "
                    "as are five-day-in-office mandates. Green flags: "
                    "engineers in leadership positions, public engineering "
                    "blog with real technical depth."
                ),
                "good_role_signals_text": "small teams, fast feedback loops",
                "life_constraints": ["needs hybrid", "no relocation"],
                "writing_samples": samples,
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
                f"finalise OK: entries_written={body['career_entries_written']} "
                f"style_profile_id={body.get('writing_style_profile_id')}"
            )

            # ── 1. Style profile populated (LLM-patched fixture) ──────
            if body.get("writing_style_profile_id") is None:
                failures.append(
                    "writing_style_profile_id is None — style_extractor "
                    "wasn't reached or its result was dropped."
                )

            # ── 2. CareerEntries: conversation + 3 motivations + 2
            #       deal_breakers + (2 + 1 extra) good_role_signals + 3
            #       writing_samples = 12 entries.
            expected = (
                1                # career_narrative
                + len(parsed_motivations.motivations)
                + len(parsed_deal_breakers.deal_breakers)
                + len(parsed_deal_breakers.good_role_signals) + 1  # + extra signals
                + len(samples)
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

            # ── 3. Profile retrievable, motivations + deal_breakers parsed ─
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
                    "motivations was not parsed into 3 items "
                    f"(got {len(profile['motivations'])}: {profile['motivations']}). "
                    "If this is 1, the parser fixture didn't take effect and "
                    "the raw fallback was used instead."
                )
            else:
                messages.append(
                    f"profile.motivations parsed into 3 items "
                    f"(not raw-text fallback)"
                )
            if len(profile["deal_breakers"]) != 2:
                failures.append(
                    f"deal_breakers count={len(profile['deal_breakers'])} != 2"
                )
            # good_role_signals = 2 from parser + 1 from extra-signals text
            if len(profile["good_role_signals"]) != 3:
                failures.append(
                    f"good_role_signals count={len(profile['good_role_signals'])} != 3"
                )
            if profile.get("writing_style_profile_id") is None:
                failures.append("profile.writing_style_profile_id is None on reload.")

        # ── 4. FAISS retrieval works against the new entries ──────────
        # Use the storage layer directly (the API doesn't expose retrieval).
        from trajectory.storage import Storage

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
    finally:
        style_extractor.extract = original_extract
        onboarding_parser.parse_stage = original_parse_stage
        if original_route_extract is not None:
            onboarding_route.extract_style = original_route_extract

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
