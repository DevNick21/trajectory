"""Smoke test — application_answer_shaper.shape on a synthetic answer.

Set SMOKE_APPLICATION_ANSWER_SHAPER_MOCK=1 to skip the live DeepSeek call.

Cost: ~$0.03 live, $0 mock.
"""

from __future__ import annotations

import os

from ._common import (
    SmokeResult,
    build_synthetic_writing_style,
    build_test_user,
    now_utc_naive,
    prepare_environment,
    require_env,
    run_smoke,
)

NAME = "application_answer_shaper"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.03


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    mock = os.getenv("SMOKE_APPLICATION_ANSWER_SHAPER_MOCK", "").lower() in {
        "1",
        "true",
        "yes",
    }
    if not mock:
        missing = require_env("DEEPSEEK_API_KEY")
        if missing:
            return [], [missing], 0.0

    messages: list[str] = []
    failures: list[str] = []

    if mock:
        messages.append("MOCK: skipped DeepSeek; would return ApplicationAnswerOutput")
        return messages, failures, 0.0

    from askpicky.memory.application_assist import classify_question
    from askpicky.schemas import AdviceSnippet, MemorySuggestion
    from askpicky.sub_agents import application_answer_shaper
    from askpicky.validators.banned_phrases import contains_banned

    user = build_test_user("uk_resident")
    style = build_synthetic_writing_style(user.user_id)
    pattern = classify_question(
        "Describe a time you influenced non-technical stakeholders.",
        "The role needs SQL dashboards and stakeholder communication.",
    )
    memories = [
        MemorySuggestion(
            memory_id="memory-smoke-1",
            memory_kind="experience_atom",
            title="Stakeholder dashboard",
            text=(
                "At Betfred, built a SQL dashboard for trading stakeholders "
                "and used weekly feedback to improve adoption."
            ),
            score=0.91,
            rationale="Exact stakeholder/dashboard match.",
            warnings=[],
        )
    ]
    advice = [
        AdviceSnippet(
            advice_id="advice-smoke-1",
            title="STAR structure",
            body="Use situation, task, action, and result in a compact answer.",
            source_url="https://nationalcareers.service.gov.uk/careers-advice/interview-advice/the-star-method",
            source_type="official",
            topic_tags=["competency", "rubric"],
            licence_status="link-and-summary",
            citation_text="National Careers Service guidance on the STAR method.",
            created_at=now_utc_naive(),
        )
    ]

    output = await application_answer_shaper.shape(
        question_text="Describe a time you influenced non-technical stakeholders.",
        raw_draft=(
            "At Betfred I built a dashboard for trading stakeholders. I asked "
            "what decisions they needed weekly, built it in SQL and Python, "
            "and kept refining it with their feedback."
        ),
        user=user,
        style_profile=style,
        question_pattern=pattern,
        memory_suggestions=memories,
        advice_snippets=advice,
        word_limit=200,
        job_context={"company_name": "Betfred", "role_title": "Senior Data Analyst"},
        session_id="smoke-application-answer-shaper",
    )

    messages.append(
        f"word_count={output.word_count} structure={output.structure_used!r}"
    )
    if not output.final_answer.strip():
        failures.append("final_answer is empty.")
    if output.word_count > 200:
        failures.append(f"word_count exceeds limit: {output.word_count}")
    for phrase in contains_banned(output.final_answer):
        failures.append(f"banned phrase in final answer: {phrase!r}")

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
