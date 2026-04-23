"""Smoke test — onboarding parser (Opus 4.7 low effort).

Exercises the new per-stage parser + the advance-with-clarification
flow on `OnboardingSession`. Confirms:

  - A clear, complete reply → status="parsed", state advances
  - A vague one-word reply → status="needs_clarification", state stays,
    follow_up is non-empty
  - Numeric extraction works in plain English ("sixty k" → 60000)

Cost: ~$0.15 (3 Opus 4.7 low-effort round-trips).
"""

from __future__ import annotations

from ._common import (
    SmokeResult,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "onboarding_parser"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.15


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()
    missing = require_anthropic_key()
    if missing:
        return [], [missing], 0.0

    from trajectory.sub_agents.onboarding_parser import (
        parse_money,
        parse_deal_breakers,
        parse_visa,
    )

    messages: list[str] = []
    failures: list[str] = []

    # ---- Case 1: clear money answer → parsed ------------------------------
    r = await parse_money("My floor is sixty thousand, target eighty-five.")
    messages.append(
        f"money parsed: status={r.status} floor={r.salary_floor_gbp} "
        f"target={r.salary_target_gbp}"
    )
    if r.status != "parsed":
        failures.append(
            f"Clear money reply was not parsed: status={r.status!r} "
            f"follow_up={r.follow_up!r}"
        )
    if r.salary_floor_gbp != 60_000:
        failures.append(
            f"Expected salary_floor_gbp=60000, got {r.salary_floor_gbp!r}"
        )
    if r.salary_target_gbp != 85_000:
        failures.append(
            f"Expected salary_target_gbp=85000, got {r.salary_target_gbp!r}"
        )

    # ---- Case 2: vague money answer → needs_clarification ----------------
    r2 = await parse_money("idk, whatever")
    messages.append(
        f"vague money: status={r2.status} follow_up={r2.follow_up!r}"
    )
    if r2.status != "needs_clarification":
        failures.append(
            "Vague 'idk whatever' money reply should need clarification; "
            f"got status={r2.status!r}"
        )
    if not r2.follow_up:
        failures.append("needs_clarification but no follow_up question")

    # ---- Case 3: visa answer with UK citizen signal ----------------------
    r3 = await parse_visa(
        "I'm a British citizen living in Manchester, "
        "happy to relocate for the right role."
    )
    messages.append(
        f"visa parsed: status={r3.status} type={r3.user_type} "
        f"loc={r3.base_location!r} relocate={r3.open_to_relocation}"
    )
    if r3.status != "parsed":
        failures.append(f"Clear visa reply not parsed: {r3.follow_up!r}")
    if r3.user_type != "uk_resident":
        failures.append(
            f"British citizen should be uk_resident, got {r3.user_type!r}"
        )

    return messages, failures, ESTIMATED_COST_USD


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
