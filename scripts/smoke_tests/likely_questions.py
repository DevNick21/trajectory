"""Smoke test — likely_questions.generate against fixture.

Validates:
  - Output is LikelyQuestionsOutput with >= 5 questions.
  - Each question has a bucket, likelihood, and a citation that resolves.
  - No banned phrases in question text.

Set SMOKE_LIKELY_QUESTIONS_MOCK=1 to skip Opus.

Cost: ~$0.30 live, $0 mock.
"""

from __future__ import annotations

import os

from ._common import (
    SmokeResult,
    build_test_user,
    load_fixture_bundle,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "likely_questions"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.30


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    mock = os.getenv("SMOKE_LIKELY_QUESTIONS_MOCK", "").lower() in {"1", "true", "yes"}
    if not mock:
        missing = require_anthropic_key()
        if missing:
            return [], [missing], 0.0

    bundle = load_fixture_bundle()
    user = build_test_user("uk_resident")

    messages: list[str] = []
    failures: list[str] = []

    if mock:
        messages.append("MOCK: skipped Opus call (would return LikelyQuestionsOutput)")
        return messages, failures, 0.0

    from trajectory.sub_agents import likely_questions
    from trajectory.validators.banned_phrases import contains_banned
    from trajectory.validators.citations import build_context, validate_output

    ctx = await build_context(
        research_bundle=bundle,
        user_id=user.user_id,
        career_entries=[],
    )
    try:
        out = await likely_questions.generate(
            jd=bundle.extracted_jd,
            research_bundle=bundle,
            user=user,
            retrieved_entries=[],
            citation_ctx=ctx,
        )
    except Exception as exc:
        failures.append(f"likely_questions.generate raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(f"questions={len(out.questions)}")
    if len(out.questions) < 5:
        failures.append(f"expected >= 5 questions; got {len(out.questions)}")
    for i, q in enumerate(out.questions):
        for phrase in contains_banned(q.question):
            failures.append(f"banned phrase in question[{i}]: {phrase!r}")

    citation_failures = validate_output(out, ctx)
    if citation_failures:
        failures.extend(f"citation: {f}" for f in citation_failures[:5])

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
