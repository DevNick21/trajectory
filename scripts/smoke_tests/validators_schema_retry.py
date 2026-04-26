"""Smoke test — schema_retry retry-with-feedback wrapper (no LLM).

Exercises:
  - Succeeds on first valid return.
  - Retries once, surfacing feedback to the retry closure.
  - Raises SchemaRetryExhausted after max_retries.

Cost: $0 (uses stub async functions, no Anthropic calls).
"""

from __future__ import annotations

from ._common import SmokeResult, prepare_environment, run_smoke

NAME = "validators_schema_retry"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from pydantic import BaseModel
    from trajectory.validators.schema_retry import (
        SchemaRetryExhausted,
        with_retry_on_invalid,
    )

    class Expected(BaseModel):
        name: str
        n: int

    messages: list[str] = []
    failures: list[str] = []

    # First-attempt success.
    calls = 0

    async def good_stub(feedback):
        nonlocal calls
        calls += 1
        return {"name": "ok", "n": 1}

    out = await with_retry_on_invalid(good_stub, Expected)
    if out.name != "ok" or out.n != 1 or calls != 1:
        failures.append(f"good_stub: unexpected state name={out.name} n={out.n} calls={calls}")
    else:
        messages.append("first-attempt success OK")

    # Invalid → valid on second attempt, feedback propagated.
    feedbacks_seen: list = []
    calls2 = 0

    async def flaky_stub(feedback):
        nonlocal calls2
        calls2 += 1
        feedbacks_seen.append(feedback)
        if calls2 == 1:
            return {"name": 123}  # missing n, wrong type
        return {"name": "good", "n": 42}

    out = await with_retry_on_invalid(flaky_stub, Expected, max_retries=2)
    if out.n != 42 or calls2 != 2:
        failures.append(f"flaky_stub: expected 2 calls + n=42; got calls={calls2} n={out.n}")
    if feedbacks_seen[0] is not None or feedbacks_seen[1] is None:
        failures.append(
            f"feedback propagation broken: first={feedbacks_seen[0]!r} second={feedbacks_seen[1]!r}"
        )
    else:
        messages.append("retry-with-feedback OK (feedback present on second attempt)")

    # Exhaustion after max_retries.
    calls3 = 0

    async def bad_stub(feedback):
        nonlocal calls3
        calls3 += 1
        return {"garbage": True}

    raised = None
    try:
        await with_retry_on_invalid(bad_stub, Expected, max_retries=1)
    except SchemaRetryExhausted as exc:
        raised = exc
    if raised is None:
        failures.append("bad_stub did not raise SchemaRetryExhausted")
    elif calls3 != 2:
        failures.append(f"bad_stub: expected 2 attempts, got {calls3}")
    else:
        messages.append(f"SchemaRetryExhausted raised after {calls3} attempts")

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
