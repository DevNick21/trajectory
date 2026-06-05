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

Cost: $0.
"""

from __future__ import annotations

from datetime import date

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
    from askpicky.api.app import create_app
    from askpicky.config import settings

    settings.demo_user_id = "smoke_onboarding_visa"

    visa_expiry = date(date.today().year + 2, 9, 30)

    app = create_app()

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
                "long-term UK career path with sponsor stability; "
                "engineering teams that ship products to global users"
            ),
            "deal_breakers_text": (
                "unsponsored roles; companies without an A-rated sponsor licence"
            ),
            "good_role_signals_text": "track record of visa renewals",
            "life_constraints": [],
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
        if "writing_style_profile_id" in body:
            failures.append(
                "onboarding finalise should not return writing_style_profile_id."
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
