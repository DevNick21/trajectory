"""Smoke test — RateLimiter sliding-window behaviour (no LLM).

Exercises:
  - intent_to_category mapping
  - forward_job bucket (5/min default) allows 5, throttles 6th
  - generator bucket (10/hr) counts independently per category
  - reset() clears state

Cost: $0.
"""

from __future__ import annotations

from ._common import SmokeResult, prepare_environment, run_smoke

NAME = "ratelimit"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from trajectory.ratelimit import RateLimiter, intent_to_category

    messages: list[str] = []
    failures: list[str] = []

    # Intent → category.
    cases = {
        "forward_job": "forward_job",
        "draft_cv": "generator",
        "draft_cover_letter": "generator",
        "predict_questions": "generator",
        "salary_advice": "generator",
        "full_prep": "generator",
        "draft_reply": "generator",
        "profile_query": "chitchat",
        "recent": "chitchat",
        "chitchat": "chitchat",
        "weird_unknown_intent": "chitchat",  # defaults to chitchat
    }
    for intent, expected in cases.items():
        got = intent_to_category(intent)
        if got != expected:
            failures.append(
                f"intent_to_category({intent!r}) = {got!r}, expected {expected!r}"
            )
    messages.append(f"intent_to_category: {len(cases)} cases checked")

    # Sliding window.
    limiter = RateLimiter()
    user_id = "smoke_ratelimit_user"
    allowed = 0
    blocked = 0
    for i in range(7):
        decision = limiter.check(user_id, "forward_job")
        if decision.allowed:
            allowed += 1
        else:
            blocked += 1
    if allowed != 5 or blocked != 2:
        failures.append(
            f"forward_job: expected 5 allowed + 2 blocked; got {allowed} + {blocked}"
        )
    else:
        messages.append(
            f"forward_job bucket: {allowed} allowed, {blocked} blocked (expected 5/2)"
        )

    # Generator bucket is independent — still fresh.
    decision = limiter.check(user_id, "draft_cv")
    if not decision.allowed:
        failures.append(
            "draft_cv blocked despite generator bucket being fresh — bucket "
            "independence broken."
        )

    # Reset clears state.
    limiter.reset(user_id)
    decision = limiter.check(user_id, "forward_job")
    if not decision.allowed:
        failures.append("forward_job still blocked after reset() for the user.")
    else:
        messages.append("reset() cleared state as expected")

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
