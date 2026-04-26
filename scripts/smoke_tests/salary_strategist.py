"""Smoke test — salary_strategist.generate against fixture.

Fabricates a JobSearchContext (urgency=HIGH, 2 recent rejections) and
asserts the recommendation lands within the ASHE band in the fixture.

Set SMOKE_SALARY_STRATEGIST_MOCK=1 to skip Opus.

Cost: ~$0.50 live, $0 mock.
"""

from __future__ import annotations

import os

from ._common import (
    SmokeResult,
    build_synthetic_writing_style,
    build_test_user,
    load_fixture_bundle,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "salary_strategist"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.50


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    mock = os.getenv("SMOKE_SALARY_STRATEGIST_MOCK", "").lower() in {"1", "true", "yes"}
    if not mock:
        missing = require_anthropic_key()
        if missing:
            return [], [missing], 0.0

    from trajectory.schemas import JobSearchContext

    bundle = load_fixture_bundle()
    user = build_test_user("uk_resident")
    style = build_synthetic_writing_style(user.user_id)
    ctx = JobSearchContext(
        user_id=user.user_id,
        urgency_level="HIGH",
        recent_rejections_count=2,
        time_since_last_offer_days=90,
        months_until_visa_expiry=None,
        applications_in_last_30_days=15,
        search_duration_months=5,
    )

    messages: list[str] = []
    failures: list[str] = []

    if mock:
        messages.append(f"MOCK: skipped Opus; context urgency={ctx.urgency_level}")
        return messages, failures, 0.0

    from trajectory.sub_agents import salary_strategist
    from trajectory.validators.citations import build_context, validate_output

    cit_ctx = await build_context(
        research_bundle=bundle,
        user_id=user.user_id,
        career_entries=[],
    )
    try:
        rec = await salary_strategist.generate(
            jd=bundle.extracted_jd,
            research_bundle=bundle,
            user=user,
            context=ctx,
            style_profile=style,
            citation_ctx=cit_ctx,
        )
    except Exception as exc:
        failures.append(f"salary_strategist.generate raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"opening={rec.opening_number} floor={rec.floor} ceiling={rec.ceiling} "
        f"confidence={rec.confidence}"
    )
    # Fixture ASHE p10/p90 = 42k/110k — recommendation should be inside
    # that for a SWE role in London.
    if not (40_000 <= rec.opening_number <= 120_000):
        failures.append(
            f"opening_number {rec.opening_number} outside plausible SWE range."
        )
    if rec.floor > rec.ceiling:
        failures.append(f"floor {rec.floor} > ceiling {rec.ceiling}")

    citation_failures = validate_output(rec, cit_ctx)
    if citation_failures:
        failures.extend(f"citation: {f}" for f in citation_failures[:5])

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
