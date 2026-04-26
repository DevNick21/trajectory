"""Smoke test — star_polisher.polish on a synthetic rough answer.

Set SMOKE_STAR_POLISHER_MOCK=1 to skip Opus.

Cost: ~$0.08 live, $0 mock.
"""

from __future__ import annotations

import os

from ._common import (
    SmokeResult,
    build_synthetic_writing_style,
    load_fixture_bundle,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "star_polisher"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.08

_ROUGH = (
    "Once when we had a bad outage in the payments service, I was on-call. "
    "I rolled back the bad deploy, wrote a post-mortem, and then we added "
    "better tests so it wouldn't happen again. Management was happy."
)


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    mock = os.getenv("SMOKE_STAR_POLISHER_MOCK", "").lower() in {"1", "true", "yes"}
    if not mock:
        missing = require_anthropic_key()
        if missing:
            return [], [missing], 0.0

    bundle = load_fixture_bundle()
    style = build_synthetic_writing_style("smoke_user")

    messages: list[str] = []
    failures: list[str] = []

    if mock:
        messages.append("MOCK: skipped Opus; would return STARPolish")
        return messages, failures, 0.0

    from trajectory.schemas import DesignedQuestion
    from trajectory.sub_agents import star_polisher
    from trajectory.validators.banned_phrases import contains_banned

    question = DesignedQuestion(
        question_text="Tell me about a time you handled a production incident.",
        rationale="Probes incident response and written communication.",
        target_gap="TECHNICAL_EVIDENCE",
        required_output_for_pack="A STAR-polished incident narrative.",
    )

    try:
        polish = await star_polisher.polish(
            question=question,
            raw_answer=_ROUGH,
            jd=bundle.extracted_jd,
            style_profile=style,
            session_id="smoke-star-polisher",
        )
    except Exception as exc:
        failures.append(f"star_polisher.polish raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"overall_confidence={polish.overall_confidence:.2f} "
        f"situation={len(polish.situation.text)}c "
        f"action={len(polish.action.text)}c"
    )
    for component_name, comp in (
        ("situation", polish.situation), ("task", polish.task),
        ("action", polish.action), ("result", polish.result),
    ):
        if not comp.text.strip():
            failures.append(f"{component_name} text is empty.")
        for phrase in contains_banned(comp.text):
            failures.append(f"banned phrase in {component_name}: {phrase!r}")

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
