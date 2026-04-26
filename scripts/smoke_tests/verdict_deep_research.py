"""Smoke test — Managed Agents verdict deep-research variant.

⚠️  HIGHER COST. Opus xhigh + Web Search + Web Fetch tool use; full
session typically $1-3 per run. Gated behind `SMOKE_VERDICT_DEEP=1`.

`verdict_deep_research` is the "money no object" verdict variant —
issues a Verdict augmented by live web information (news, leaver
patterns, recent activity) instead of relying solely on the static
research bundle. Wired into `orchestrator.handle_forward_job` as the
second slot of the verdict ensemble when both
`enable_verdict_ensemble=True` AND
`enable_verdict_ensemble_deep_research=True`. Both default off.

Until this smoke landed the deep-research path was structurally
untested in CI — the only coverage was the symmetric ensemble path
(two parallel `verdict_agent.generate` calls).

Asserts:
  - run() returns a valid Verdict against the fixture bundle
  - schema fields are populated (decision, confidence_pct, reasoning)
  - Rule 2: GO + hard_blocker is impossible (the verdict agent's
    own post_validate guard runs inside `call_with_tools`)
  - cost log row written tagged `verdict_deep_research`
"""

from __future__ import annotations

import asyncio
import os

from ._common import (
    SmokeResult,
    build_test_user,
    load_fixture_bundle,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "verdict_deep_research"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 2.50

_GATE_ENV = "SMOKE_VERDICT_DEEP"


async def _body() -> tuple[list[str], list[str], float]:
    messages: list[str] = []
    failures: list[str] = []

    if os.environ.get(_GATE_ENV, "") != "1":
        messages.append(
            f"skipped — set {_GATE_ENV}=1 to opt into the paid verdict "
            "deep-research session (~$1-3)"
        )
        return messages, failures, 0.0

    prepare_environment()
    missing = require_anthropic_key()
    if missing:
        return [], [missing], 0.0

    from trajectory.managed.verdict_deep_research import run as run_deep
    from trajectory.storage import total_cost_usd

    bundle = load_fixture_bundle()
    user = build_test_user("uk_resident")

    cost_before = await total_cost_usd()

    try:
        verdict = await run_deep(
            user=user,
            research_bundle=bundle,
            session_id="smoke-verdict-deep",
        )
    except Exception as exc:
        failures.append(f"verdict_deep_research raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"decision={verdict.decision} "
        f"confidence={verdict.confidence_pct}% "
        f"blockers={len(verdict.hard_blockers)} "
        f"stretch={len(verdict.stretch_concerns)} "
        f"reasoning_points={len(verdict.reasoning)}"
    )
    messages.append(f"headline: {verdict.headline}")

    if verdict.decision not in {"GO", "NO_GO"}:
        failures.append(f"decision={verdict.decision!r} not in GO/NO_GO")
    if not (0 <= verdict.confidence_pct <= 100):
        failures.append(
            f"confidence_pct={verdict.confidence_pct} out of range"
        )
    if len(verdict.reasoning) < 3:
        failures.append(
            f"reasoning has {len(verdict.reasoning)} points; "
            "Rule: at least 3"
        )
    # Rule 2 — the post_validate inside `call_with_tools` should
    # reject this combo, and a belt-and-braces flip would have fired.
    # Either way, the final verdict can't carry GO + hard_blockers.
    if verdict.decision == "GO" and verdict.hard_blockers:
        failures.append(
            f"GO with {len(verdict.hard_blockers)} hard blocker(s) — "
            "Rule 2 violation escaped the deep-research path"
        )

    # Each reasoning point should carry a citation (no invented data —
    # the deep-research path explicitly requires citations).
    for i, r in enumerate(verdict.reasoning):
        if r.citation is None:
            failures.append(
                f"reasoning[{i}] missing citation — deep-research "
                "is supposed to cite every claim"
            )

    cost_after = await total_cost_usd()
    delta = cost_after - cost_before
    if delta <= 0:
        failures.append(
            f"llm_cost_log delta={delta:.4f} — usage didn't log; the "
            "`call_with_tools` adapter may have skipped log_llm_cost."
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
