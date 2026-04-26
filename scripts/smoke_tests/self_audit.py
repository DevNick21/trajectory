"""Smoke test — self_audit.run on a CV with a planted banned phrase.

Expects the audit to at minimum flag the planted phrase. A clean audit
on content that contains 'passionate' would indicate the banned-phrase
detection pipeline is broken.

Set SMOKE_SELF_AUDIT_MOCK=1 to skip Opus.

Cost: ~$0.10 live, $0 mock.
"""

from __future__ import annotations

import os

from ._common import (
    SmokeResult,
    build_synthetic_cv_output,
    build_synthetic_writing_style,
    load_fixture_bundle,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "self_audit"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.10


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    mock = os.getenv("SMOKE_SELF_AUDIT_MOCK", "").lower() in {"1", "true", "yes"}
    if not mock:
        missing = require_anthropic_key()
        if missing:
            return [], [missing], 0.0

    bundle = load_fixture_bundle()
    style = build_synthetic_writing_style("smoke_user")
    cv = build_synthetic_cv_output()
    # Plant a banned phrase in the summary so a correct audit flags it.
    cv.professional_summary = (
        "Passionate backend engineer with a proven track record of "
        "shipping production systems."
    )

    messages: list[str] = []
    failures: list[str] = []

    if mock:
        messages.append("MOCK: skipped Opus; would return SelfAuditReport with ≥1 flag")
        return messages, failures, 0.0

    from trajectory.sub_agents import self_audit

    try:
        report = await self_audit.run(
            generated=cv,
            research_bundle=bundle,
            style_profile=style,
            company_name=bundle.company_research.company_name,
            session_id="smoke-self-audit",
        )
    except Exception as exc:
        failures.append(f"self_audit.run raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"flags={len(report.flags)} hard_reject={report.hard_reject} "
        f"style_conformance={report.overall_style_conformance}/10"
    )
    if not report.flags:
        failures.append(
            "self_audit returned zero flags on content containing 'passionate' "
            "and 'proven track record' — the audit is not catching cliches."
        )
    else:
        kinds = {f.flag_type for f in report.flags}
        messages.append(f"flag kinds: {sorted(kinds)}")

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
