"""Smoke test — Managed Agents reviews investigator.

⚠️  HIGHER COST. A full session at Opus xhigh costs roughly $1-3.
Gated behind `SMOKE_MANAGED_REVIEWS=1` so casual runs don't burn credits.

The reviews_investigator MA session replaces the no-op jobspy path
(jobspy 1.1.13 dropped Glassdoor support; Indeed returns 403 anti-bot).
Today the path is structurally dead in production —
`enable_managed_reviews_investigator` defaults to False and the legacy
fallback returns `[]`. This smoke is the only test that exercises the
session end-to-end.

Asserts:
  - run() returns a ReviewsInvestigatorOutput
  - excerpts each have a non-empty source + text
  - content shield ran (excerpts are post-shield)
  - cost log row was written
  - JSON parser tolerated whatever shape the agent emitted (PROCESS Entry 45)
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

NAME = "managed_reviews"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 2.00  # Opus xhigh, multi-step web

# Stable, well-known UK employer with abundant public review surface.
_TARGET_COMPANY = "Monzo Bank"
_TARGET_DOMAIN = "monzo.com"
_GATE_ENV = "SMOKE_MANAGED_REVIEWS"


async def _body() -> tuple[list[str], list[str], float]:
    messages: list[str] = []
    failures: list[str] = []

    if os.environ.get(_GATE_ENV, "") != "1":
        messages.append(
            f"skipped — set {_GATE_ENV}=1 to opt into the paid MA "
            "reviews session (~$1-3)"
        )
        return messages, failures, 0.0

    prepare_environment()
    missing = require_anthropic_key()
    if missing:
        return [], [missing], 0.0

    from trajectory.managed.reviews_investigator import (
        ReviewsInvestigatorFailed,
        run as run_reviews,
    )
    from trajectory.storage import total_cost_usd

    cost_before = await total_cost_usd()

    try:
        output = await run_reviews(
            company_name=_TARGET_COMPANY,
            company_domain=_TARGET_DOMAIN,
            session_id="smoke-managed-reviews",
        )
    except ReviewsInvestigatorFailed as exc:
        failures.append(f"reviews_investigator raised: {exc}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"company={output.company_name!r} "
        f"excerpts={len(output.excerpts)} "
        f"notes_chars={len(output.investigation_notes)}"
    )

    if not output.company_name:
        failures.append("company_name was empty")

    # The agent may legitimately return zero excerpts (sources were
    # banned or unreachable). Don't fail on that — but if any are
    # present, sanity-check their shape.
    for i, ex in enumerate(output.excerpts):
        if not ex.source:
            failures.append(f"excerpt[{i}] missing source")
        if not ex.text or len(ex.text) < 10:
            failures.append(
                f"excerpt[{i}] text too short ({len(ex.text)} chars) — "
                "agent or content shield trimmed too aggressively"
            )

    # Cost log assertion — proves log_llm_cost wired correctly for the
    # session lifecycle (cumulative usage from sessions.retrieve()).
    cost_after = await total_cost_usd()
    delta = cost_after - cost_before
    if delta <= 0:
        failures.append(
            f"llm_cost_log delta is {delta:.4f} — session usage didn't "
            "log; sessions.retrieve() may have failed silently."
        )
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
