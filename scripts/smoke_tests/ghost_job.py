"""Smoke test — ghost_job_detector.score on fixture (LLM-backed).

Exercises the ghost-job JD scorer (Opus 4.7 xhigh) + signal
combination. Fixture is the vanilla research bundle: should return
LIKELY_REAL with HIGH confidence.

Set SMOKE_GHOST_JOB_MOCK=1 to skip the Opus call and fabricate a
fixture GhostJobAssessment (asserts wiring only).

Cost: ~$0.15 live, $0 mock.
"""

from __future__ import annotations

import os

from ._common import (
    SmokeResult,
    load_fixture_bundle,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "ghost_job"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.15


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    mock = os.getenv("SMOKE_GHOST_JOB_MOCK", "").lower() in {"1", "true", "yes"}
    if not mock:
        missing = require_anthropic_key()
        if missing:
            return [], [missing], 0.0

    from trajectory.sub_agents import ghost_job_detector

    bundle = load_fixture_bundle()
    messages: list[str] = []
    failures: list[str] = []

    if mock:
        # Import the existing fixture assessment from the bundle — it's
        # shaped right; smoke is just verifying imports + Pydantic plumb.
        fixture = bundle.ghost_job
        messages.append(
            f"MOCK: fixture probability={fixture.probability} confidence={fixture.confidence}"
        )
        return messages, failures, 0.0

    try:
        assessment = await ghost_job_detector.score(
            jd=bundle.extracted_jd,
            company_research=bundle.company_research,
            companies_house=bundle.companies_house,
            job_url="https://example.com/smoke/job",
            session_id="smoke-ghost",
        )
    except Exception as exc:
        failures.append(f"ghost_job_detector.score raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"probability={assessment.probability} confidence={assessment.confidence} "
        f"signals={len(assessment.signals)} "
        f"specificity_score={assessment.raw_jd_score.specificity_score:.1f}"
    )
    if assessment.probability not in {"LIKELY_GHOST", "POSSIBLE_GHOST", "LIKELY_REAL"}:
        failures.append(f"unexpected probability: {assessment.probability!r}")
    if assessment.raw_jd_score.specificity_score < 2.5:
        failures.append(
            f"fixture JD has named manager + specifics but scored low: "
            f"{assessment.raw_jd_score.specificity_score:.1f}"
        )

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
