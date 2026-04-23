"""Smoke test — verdict agent against the fixture bundle.

Exercises:
  - Anthropic SDK auth + tool_use + extended thinking wiring
  - verdict system prompt end-to-end against a realistic bundle
  - post_validate: citation validator, reasoning-point floor,
    GO-with-hard-blockers rejection + retry feedback
  - _enforce_no_go_with_blockers belt-and-braces
  - Storage round-trip (verdict persisted then reloaded)

Set SMOKE_TEST_MOCK=1 to run the same wiring against a fixture
verdict — useful when iterating on orchestrator/storage without
burning Opus credits.

Cost: ~$0.50-$1.50 live, $0 mock.
"""

from __future__ import annotations

import os

from ._common import (
    SmokeResult,
    build_test_session,
    build_test_user,
    load_fixture_bundle,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "verdict"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 1.00


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    mock = os.getenv("SMOKE_TEST_MOCK", "").lower() in {"1", "true", "yes"}
    if not mock:
        missing = require_anthropic_key()
        if missing:
            return [], [missing], 0.0

    from trajectory.storage import Storage
    from trajectory.sub_agents import verdict as verdict_agent

    bundle = load_fixture_bundle()
    user = build_test_user("visa_holder")
    session = build_test_session(user.user_id)

    storage = Storage()
    await storage.initialise()
    await storage.save_user_profile(user)
    await storage.save_session(session)

    messages: list[str] = []
    failures: list[str] = []

    messages.append(
        f"fixture: {bundle.extracted_jd.role_title} @ "
        f"{bundle.company_research.company_name} "
        f"({len(bundle.company_research.scraped_pages)} pages)"
    )
    messages.append(f"mode: {'MOCK' if mock else 'LIVE Opus 4.7 xhigh'}")

    try:
        verdict = await verdict_agent.generate(
            user=user,
            research_bundle=bundle,
            retrieved_entries=[],
            session_id=session.session_id,
        )
    except Exception as exc:
        failures.append(f"verdict.generate raised: {exc!r}")
        return messages, failures, 0.0 if mock else ESTIMATED_COST_USD

    messages.append(
        f"decision={verdict.decision} confidence={verdict.confidence_pct}% "
        f"blockers={len(verdict.hard_blockers)} "
        f"stretch={len(verdict.stretch_concerns)} "
        f"reasoning_points={len(verdict.reasoning)}"
    )
    messages.append(f"headline: {verdict.headline}")

    if verdict.decision not in {"GO", "NO_GO"}:
        failures.append(f"decision={verdict.decision!r} not in GO/NO_GO")
    if not (0 <= verdict.confidence_pct <= 100):
        failures.append(f"confidence_pct={verdict.confidence_pct} out of range")
    if len(verdict.headline.split()) > 12:
        failures.append(f"headline exceeds 12 words: {verdict.headline!r}")
    if len(verdict.reasoning) < 3:
        failures.append(f"reasoning has {len(verdict.reasoning)} < 3 points")
    if verdict.decision == "GO" and verdict.hard_blockers:
        failures.append(
            f"GO with {len(verdict.hard_blockers)} hard_blocker(s) — "
            "CLAUDE.md Rule 2 violation"
        )
    for i, r in enumerate(verdict.reasoning):
        if r.citation is None:
            failures.append(f"reasoning[{i}] missing citation")

    # Storage round-trip — exercises H7's dict/model unification.
    await storage.save_verdict(session.session_id, verdict)
    reloaded = await storage.get_session(session.session_id)
    if reloaded is None or reloaded.verdict is None:
        failures.append("Storage round-trip lost the verdict.")
    elif not hasattr(reloaded.verdict, "decision"):
        failures.append(
            f"Storage round-trip returned non-Verdict: {type(reloaded.verdict)!r}"
        )

    await storage.close()
    return messages, failures, 0.0 if mock else ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
