"""Generic retry-with-feedback wrapper.

`llm.call_agent` already contains the primary retry loop. This module
exposes that pattern as a standalone helper for callers that bypass
`call_agent` (e.g. ad-hoc scripts, the self-audit rewrite loop, tests).
"""

from __future__ import annotations

from typing import Awaitable, Callable, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class SchemaRetryExhausted(RuntimeError):
    pass


async def with_retry_on_invalid(
    agent_call: Callable[[str | None], Awaitable[dict]],
    expected_schema: type[T],
    max_retries: int = 2,
) -> T:
    """Invoke `agent_call(feedback)` until it returns a dict that validates
    against `expected_schema`.

    `agent_call` receives the previous-attempt feedback string (or None on
    the first try) and must return a dict.
    """
    feedback: str | None = None
    for attempt in range(max_retries + 1):
        raw = await agent_call(feedback)
        try:
            return expected_schema.model_validate(raw)
        except ValidationError as ve:
            feedback = (
                f"Previous attempt did not validate against "
                f"{expected_schema.__name__}: {ve}"
            )
    raise SchemaRetryExhausted(
        f"Exhausted {max_retries + 1} attempts for {expected_schema.__name__}. "
        f"Last feedback: {feedback}"
    )
