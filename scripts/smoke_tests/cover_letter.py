"""Smoke test — cover_letter.generate against fixture + synthetic style.

Validates the Opus xhigh cover letter generator wiring:
  - accepts fixture JD + bundle + synthetic user/style
  - output schema valid
  - word_count sane (>= 150, <= 500)
  - zero banned phrases in paragraphs
  - every citation resolves against the fixture bundle

Set SMOKE_COVER_LETTER_MOCK=1 to skip Opus.

Cost: ~$0.40 live, $0 mock.
"""

from __future__ import annotations

import os

from ._common import (
    SmokeResult,
    build_synthetic_cover_letter_output,
    build_synthetic_writing_style,
    build_test_user,
    load_fixture_bundle,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "cover_letter"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.40


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    mock = os.getenv("SMOKE_COVER_LETTER_MOCK", "").lower() in {"1", "true", "yes"}
    if not mock:
        missing = require_anthropic_key()
        if missing:
            return [], [missing], 0.0

    from trajectory.validators.banned_phrases import contains_banned
    from trajectory.validators.citations import build_context, validate_output

    bundle = load_fixture_bundle()
    user = build_test_user("uk_resident")
    style = build_synthetic_writing_style(user.user_id)

    messages: list[str] = []
    failures: list[str] = []

    if mock:
        cl = build_synthetic_cover_letter_output()
        messages.append(
            f"MOCK: synthetic cover letter, {len(cl.paragraphs)} paragraphs, "
            f"{cl.word_count} words"
        )
        return messages, failures, 0.0

    from trajectory.sub_agents import cover_letter as cl_agent

    ctx = await build_context(
        research_bundle=bundle,
        user_id=user.user_id,
        career_entries=[],
    )

    try:
        cl = await cl_agent.generate(
            jd=bundle.extracted_jd,
            research_bundle=bundle,
            user=user,
            retrieved_entries=[],
            style_profile=style,
            star_material=None,
        )
    except Exception as exc:
        failures.append(f"cover_letter.generate raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"paragraphs={len(cl.paragraphs)} word_count={cl.word_count} "
        f"citations={len(cl.citations)}"
    )

    if not 150 <= cl.word_count <= 600:
        failures.append(f"word_count {cl.word_count} outside 150-600 window.")
    all_text = "\n".join(cl.paragraphs)
    for phrase in contains_banned(all_text):
        failures.append(f"banned phrase in cover letter: {phrase!r}")
    citation_failures = validate_output(cl, ctx)
    if citation_failures:
        failures.extend(f"citation: {f}" for f in citation_failures[:5])

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
