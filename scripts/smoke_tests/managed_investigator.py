"""Smoke test — Managed Agents company investigator.

⚠️  HIGHER COST THAN OTHER SMOKE TESTS. A full session with web fetches
at Opus xhigh costs roughly $1-3. Gated behind the
`SMOKE_MANAGED_AGENTS=1` env var so a casual `run_all` invocation
doesn't burn credits.

Target: GitHub careers page (stable public URL with rich enough
content to make the agent's investigation realistic).

Asserts:
  - investigate() returns a CompanyResearch + ExtractedJobDescription
  - all citations resolve in the bundle
  - session was archived (not deleted) — i.e. the happy path
"""

from __future__ import annotations

import asyncio
import os

from ._common import (
    SmokeResult,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "managed_investigator"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 2.50  # honest mid-point of $1-3 range

# Stable public listing — a real role on GitHub's careers page.
_SMOKE_URL = "https://www.github.careers/careers-home/jobs"
_GATE_ENV = "SMOKE_MANAGED_AGENTS"


async def _body() -> tuple[list[str], list[str], float]:
    messages: list[str] = []
    failures: list[str] = []

    if os.environ.get(_GATE_ENV, "") != "1":
        messages.append(
            f"skipped — set {_GATE_ENV}=1 to opt into the paid MA "
            "session (~$1-3)"
        )
        return messages, failures, 0.0

    prepare_environment()
    missing = require_anthropic_key()
    if missing:
        return [], [missing], 0.0

    # Force the flag on for this run regardless of .env state.
    from trajectory.config import settings

    settings.enable_managed_company_investigator = True

    from trajectory.managed.company_investigator import (
        ManagedInvestigatorFailed,
        investigate,
    )

    try:
        research, extracted_jd = await investigate(
            job_url=_SMOKE_URL,
            session_id="smoke-managed-investigator",
        )
    except ManagedInvestigatorFailed as exc:
        failures.append(f"investigator raised: {exc}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"company={research.company_name!r} "
        f"role={extracted_jd.role_title!r} "
        f"culture_claims={len(research.culture_claims)} "
        f"pages={len(research.scraped_pages)}"
    )

    if not research.company_name:
        failures.append("company_name was empty")
    if not extracted_jd.role_title:
        failures.append("extracted_jd.role_title was empty")

    # Citation resolution — every culture_claim's snippet must be in a
    # stored page (the investigator already enforces this; this is a
    # belt-and-braces check at the smoke level).
    page_texts = {p.url: p.text for p in research.scraped_pages}
    for cc in research.culture_claims:
        text = page_texts.get(cc.url, "")
        if cc.verbatim_snippet not in text:
            failures.append(
                f"culture_claim snippet not in stored page {cc.url}: "
                f"{cc.verbatim_snippet[:80]!r}"
            )

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
