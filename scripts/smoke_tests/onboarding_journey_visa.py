"""Smoke test — full web onboarding journey for a visa_holder.

The visa_holder branch is the Problem Statement's sharper differentiator
and was entirely uncovered before this test. Asserts that visa-specific
fields make it from the wizard payload all the way to a UserProfile that
the verdict agent's Rule 2 hard-blocker matrix can read.

Specifically:
  - `user_type=visa_holder` lands on the profile.
  - `visa_route` + `visa_expiry` populate `UserProfile.visa_status`.
  - `nationality` populates (used by verdict context downstream).
  - The Phase-1 sponsor_register / soc_check branches in the orchestrator
    (gated on `user.user_type == 'visa_holder'`) would fire — verified by
    asserting the profile shape, not by re-running forward_journey here.

Cost: $0 (style_extractor + parse_stage both patched to fixtures).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from ._common import (
    SmokeResult,
    prepare_environment,
    run_smoke,
)

NAME = "onboarding_journey_visa"
REQUIRES_LIVE_LLM = False
ESTIMATED_COST_USD = 0.0


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    messages: list[str] = []
    failures: list[str] = []

    from fastapi.testclient import TestClient
    from trajectory.api.app import create_app
    from trajectory.api.routes import onboarding as onboarding_route
    from trajectory.config import settings
    from trajectory.schemas import (
        DealBreakersParseResult,
        MotivationsParseResult,
        WritingStyleProfile,
    )
    from trajectory.sub_agents import onboarding_parser, style_extractor

    settings.demo_user_id = "smoke_onboarding_visa"

    parsed_motivations = MotivationsParseResult(
        status="parsed",
        motivations=[
            "long-term UK career path with sponsor stability",
            "engineering teams that ship products to global users",
        ],
        drains=["uncertainty about visa renewals", "siloed teams"],
    )
    parsed_deal_breakers = DealBreakersParseResult(
        status="parsed",
        deal_breakers=[
            "unsponsored roles",
            "companies without an A-rated sponsor licence",
        ],
        good_role_signals=["A-rated sponsor", "track record of visa renewals"],
    )

    fixture_style = WritingStyleProfile(
        profile_id="smoke_onboarding_visa_style",
        user_id=settings.demo_user_id,
        tone="precise, technical, calm",
        sentence_length_pref="medium",
        formality_level=7,
        hedging_tendency="direct",
        signature_patterns=["leads with the constraint, then the action"],
        avoided_patterns=["passive voice"],
        examples=[],
        source_sample_ids=["sample_0"],
        sample_count=1,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    original_extract = style_extractor.extract
    original_parse_stage = onboarding_parser.parse_stage
    original_route_extract = getattr(onboarding_route, "extract_style", None)

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
    if original_route_extract is not None:
        onboarding_route.extract_style = _fake_extract

    visa_expiry = date(date.today().year + 2, 9, 30)

    app = create_app()

    try:
        with TestClient(app) as client:
            payload = {
                "name": "Adaeze Smoke",
                "user_type": "visa_holder",
                "visa_route": "graduate",
                "visa_expiry": visa_expiry.isoformat(),
                "nationality": "Nigerian",
                "base_location": "Manchester",
                "salary_floor": 45_000,
                "salary_target": 65_000,
                "current_employment": "EMPLOYED",
                "search_duration_months": 6,
                "motivations_text": (
                    "I want a long-term UK career path with a stable sponsor "
                    "and engineering teams that ship products to global users."
                ),
                "deal_breakers_text": (
                    "Unsponsored roles or companies without an A-rated "
                    "sponsor licence are non-starters."
                ),
                "good_role_signals_text": "track record of visa renewals",
                "life_constraints": [],
                "writing_samples": [
                    "Took the lead on the schema migration: planned the "
                    "rollout, paired with QA on the smoke deck, kept the "
                    "rollback bookmarked all weekend."
                ],
                "career_narrative": (
                    "Five years backend (Java + Kotlin). Graduated MSc Comp "
                    "Sci 2023. Currently on the Graduate visa, looking for "
                    "Skilled Worker sponsorship before it expires."
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

            # ── Profile reload + visa-specific assertions ──────────────
            resp = client.get("/api/profile")
            if resp.status_code != 200:
                failures.append(f"GET /api/profile -> {resp.status_code}")
                return messages, failures, 0.0
            profile = resp.json()

            if profile["user_type"] != "visa_holder":
                failures.append(
                    f"user_type={profile['user_type']!r} != 'visa_holder' "
                    "— the visa branch (Rule 2) won't fire downstream."
                )
            else:
                messages.append("profile.user_type=visa_holder")

            visa_status = profile.get("visa_status")
            if not visa_status:
                failures.append(
                    "profile.visa_status is None on a visa_holder onboarding "
                    "— SponsorStatus / SOC checks won't get the right context."
                )
            else:
                if visa_status.get("route") != "graduate":
                    failures.append(
                        f"visa_status.route={visa_status.get('route')!r} != 'graduate'"
                    )
                if visa_status.get("expiry_date") != visa_expiry.isoformat():
                    failures.append(
                        f"visa_status.expiry_date={visa_status.get('expiry_date')!r} "
                        f"!= {visa_expiry.isoformat()!r}"
                    )
                if not failures:
                    messages.append(
                        f"profile.visa_status: route=graduate, "
                        f"expiry={visa_status.get('expiry_date')}"
                    )

            if profile.get("nationality") != "Nigerian":
                failures.append(
                    f"profile.nationality={profile.get('nationality')!r} "
                    "!= 'Nigerian' — verdict's nationality grant-rate "
                    "context will be missing this signal."
                )
            else:
                messages.append("profile.nationality=Nigerian carried through")

            if profile["base_location"] != "Manchester":
                failures.append(
                    f"profile.base_location={profile['base_location']!r}"
                )
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
