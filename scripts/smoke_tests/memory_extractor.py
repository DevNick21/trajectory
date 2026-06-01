"""Smoke test — memory_extractor.extract on an approved answer.

Set SMOKE_MEMORY_EXTRACTOR_MOCK=1 to skip the live DeepSeek call.

Cost: ~$0.02 live, $0 mock.
"""

from __future__ import annotations

import os

from ._common import (
    SmokeResult,
    build_test_user,
    prepare_environment,
    require_env,
    run_smoke,
)

NAME = "memory_extractor"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.02


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    mock = os.getenv("SMOKE_MEMORY_EXTRACTOR_MOCK", "").lower() in {
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
        messages.append("MOCK: skipped DeepSeek; would return MemoryExtractionOutput")
        return messages, failures, 0.0

    from askpicky.memory.application_assist import build_answer_attempt
    from askpicky.sub_agents import memory_extractor

    user = build_test_user("uk_resident")
    attempt = build_answer_attempt(
        user=user,
        question_text="Describe a time you influenced non-technical stakeholders.",
        question_type="competency",
        raw_draft=(
            "At Betfred I built a dashboard for trading stakeholders. I used "
            "SQL and Python, gathered feedback from the trading desk, and "
            "made reporting easier to discuss in planning."
        ),
        final_answer=(
            "At Betfred, I built a SQL and Python dashboard for trading "
            "stakeholders, using weekly feedback from the trading desk to "
            "make reporting clearer for planning conversations."
        ),
        company_name="Betfred",
        role_title="Senior Data Analyst",
    )

    output = await memory_extractor.extract(
        attempt=attempt,
        session_id="smoke-memory-extractor",
    )
    messages.append(
        f"atoms={len(output.experience_atoms)} stories={len(output.story_frames)} "
        f"edges={len(output.memory_edges)}"
    )
    if not output.experience_atoms:
        failures.append("memory_extractor returned no experience atoms.")
    for atom in output.experience_atoms:
        if len(atom.text.split()) > 40:
            failures.append(f"atom too long: {atom.text!r}")

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
