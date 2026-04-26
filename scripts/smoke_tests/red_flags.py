"""Smoke test — red_flags.detect on fixture (LLM-backed).

Runs the red-flags detector (Opus xhigh) against the fixture's
company_research + companies_house. Expected: few or zero flags for
the fixture (which depicts a healthy company).

Set SMOKE_RED_FLAGS_MOCK=1 to skip the Opus call.

Cost: ~$0.10 live, $0 mock.
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

NAME = "red_flags"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.10


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    mock = os.getenv("SMOKE_RED_FLAGS_MOCK", "").lower() in {"1", "true", "yes"}
    if not mock:
        missing = require_anthropic_key()
        if missing:
            return [], [missing], 0.0

    bundle = load_fixture_bundle()
    messages: list[str] = []
    failures: list[str] = []

    if mock:
        messages.append(
            f"MOCK: fixture red_flags has {len(bundle.red_flags.flags)} flag(s)"
        )
        return messages, failures, 0.0

    from trajectory.sub_agents import red_flags as rf

    try:
        report = await rf.detect(
            company_research=bundle.company_research,
            companies_house=bundle.companies_house,
            reviews=None,
            session_id="smoke-red-flags",
        )
    except Exception as exc:
        failures.append(f"red_flags.detect raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"flags={len(report.flags)} checked={report.checked} "
        f"source_status={report.source_status}"
    )
    if not report.checked:
        failures.append("RedFlagsReport.checked was False after a successful run.")

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
