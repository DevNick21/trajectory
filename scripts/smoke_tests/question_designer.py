"""Smoke test — question_designer.generate (Opus xhigh).

Builds a synthetic Verdict + fixture bundle + test user, asserts the
agent returns exactly 3 DesignedQuestions (AGENTS.md contract).

Set SMOKE_QUESTION_DESIGNER_MOCK=1 to skip Opus.

Cost: ~$0.15 live, $0 mock.
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

NAME = "question_designer"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.15


def _synthetic_verdict():
    from trajectory.schemas import (
        Citation,
        MotivationFitReport,
        ReasoningPoint,
        Verdict,
    )

    cit = Citation(
        kind="url_snippet",
        url="https://acmetech.io/careers",
        verbatim_snippet="Our engineering team ships autonomously.",
    )
    return Verdict(
        decision="GO",
        confidence_pct=75,
        headline="Strong fit with minor stretch on Kubernetes depth.",
        reasoning=[
            ReasoningPoint(
                claim="Company values align",
                supporting_evidence="Acme explicitly calls out autonomous shipping.",
                citation=cit,
            ),
            ReasoningPoint(
                claim="Salary is in the posted band",
                supporting_evidence="Posted band £70k-£90k matches user's target.",
                citation=cit,
            ),
            ReasoningPoint(
                claim="Sponsor register status is active",
                supporting_evidence="Sponsor register shows LISTED.",
                citation=cit,
            ),
        ],
        hard_blockers=[],
        stretch_concerns=[],
        motivation_fit=MotivationFitReport(
            motivation_evaluations=[],
            deal_breaker_evaluations=[],
            good_role_signal_evaluations=[],
        ),
        estimated_callback_probability="MEDIUM",
    )


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    mock = os.getenv("SMOKE_QUESTION_DESIGNER_MOCK", "").lower() in {"1", "true", "yes"}
    if not mock:
        missing = require_anthropic_key()
        if missing:
            return [], [missing], 0.0

    bundle = load_fixture_bundle()
    user = build_test_user("uk_resident")

    messages: list[str] = []
    failures: list[str] = []

    if mock:
        messages.append("MOCK: skipped Opus; would return a 3-question QuestionSet")
        return messages, failures, 0.0

    from trajectory.sub_agents import question_designer

    verdict = _synthetic_verdict()

    try:
        qs = await question_designer.generate(
            verdict=verdict,
            research_bundle=bundle,
            user=user,
            retrieved_entries=[],
            session_id="smoke-question-designer",
        )
    except Exception as exc:
        failures.append(f"question_designer.generate raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(f"questions={len(qs.questions)}")
    if len(qs.questions) != 3:
        failures.append(f"expected exactly 3 questions; got {len(qs.questions)}")
    for i, q in enumerate(qs.questions):
        if not q.question_text.strip():
            failures.append(f"question[{i}] has empty text")
        if not q.rationale.strip():
            failures.append(f"question[{i}] has empty rationale")

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
