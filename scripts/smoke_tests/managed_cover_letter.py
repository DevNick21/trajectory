"""Smoke test — managed cover_letter session (PROCESS Entry 45).

Live-web-equipped variant: dispatches to call_in_session("cover_letter_managed").
Gated behind SMOKE_MANAGED_COVER_LETTER=1. Costs ~$0.40-0.80 depending on
how many web fetches the agent decides to do.

Asserts:
  - run() returns a CoverLetterOutput
  - paragraphs non-empty, word_count in 150-600 window
  - at least one citation present
  - no banned phrases
  - cost log row was written (delta > 0)
"""

from __future__ import annotations

import asyncio
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

NAME = "managed_cover_letter"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.50
_GATE_ENV = "SMOKE_MANAGED_COVER_LETTER"


async def _body() -> tuple[list[str], list[str], float]:
    messages: list[str] = []
    failures: list[str] = []

    if os.environ.get(_GATE_ENV, "") != "1":
        messages.append(
            f"skipped — set {_GATE_ENV}=1 to opt into the paid managed "
            "cover-letter session (~$0.40-0.80)"
        )
        return messages, failures, 0.0

    prepare_environment()
    missing = require_anthropic_key()
    if missing:
        return [], [missing], 0.0

    from trajectory.llm import call_in_session
    from trajectory.storage import total_cost_usd
    from trajectory.validators.banned_phrases import contains_banned

    bundle = load_fixture_bundle()
    user = build_test_user("uk_resident")
    style = build_synthetic_writing_style(user.user_id)

    cost_before = await total_cost_usd()

    try:
        cl = await call_in_session(
            "cover_letter_managed",
            jd=bundle.extracted_jd,
            research_bundle=bundle,
            user=user,
            retrieved_entries=[],
            style_profile=style,
            star_material=None,
            session_id="smoke-managed-cover-letter",
        )
    except Exception as exc:
        failures.append(f"call_in_session raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"paragraphs={len(cl.paragraphs)} word_count={cl.word_count} "
        f"citations={len(cl.citations)}"
    )

    if not cl.paragraphs:
        failures.append("paragraphs empty")
    if not 150 <= cl.word_count <= 600:
        failures.append(f"word_count {cl.word_count} outside 150-600 window")
    if not cl.citations:
        failures.append("no citations attached — managed live fetch should produce >=1")

    body = "\n".join(cl.paragraphs)
    for phrase in contains_banned(body):
        failures.append(f"banned phrase: {phrase!r}")

    cost_after = await total_cost_usd()
    delta = cost_after - cost_before
    if delta <= 0:
        failures.append(f"llm_cost_log delta {delta:.4f} — cost not logged")
    else:
        messages.append(f"cost log delta: ${delta:.4f}")

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
