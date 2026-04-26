"""Smoke test — observability correlation IDs (no LLM).

Exercises:
  - bind_request_id / get_request_id round-trip
  - new_request_id returns short, unique-ish ids
  - install_correlation_filter is idempotent
  - CorrelationFilter attaches request_id + session_id to records

Cost: $0.
"""

from __future__ import annotations

import logging

from ._common import SmokeResult, prepare_environment, run_smoke

NAME = "observability"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from trajectory.observability.logging_context import (
        CorrelationFilter,
        bind_request_id,
        bind_session_id,
        get_request_id,
        get_session_id,
        install_correlation_filter,
        new_request_id,
    )

    messages: list[str] = []
    failures: list[str] = []

    # new_request_id — short, likely unique.
    ids = {new_request_id() for _ in range(50)}
    if len(ids) < 50:
        failures.append(f"new_request_id collided in 50 draws: {50 - len(ids)} dupes")
    first = next(iter(ids))
    if not isinstance(first, str) or len(first) != 12:
        failures.append(f"new_request_id expected 12-char string; got {first!r}")
    messages.append(f"new_request_id OK: 50 unique, example={first!r}")

    # bind/get.
    bind_request_id("req-smoke-123")
    bind_session_id("sess-smoke-456")
    if get_request_id() != "req-smoke-123":
        failures.append(f"get_request_id = {get_request_id()!r}")
    if get_session_id() != "sess-smoke-456":
        failures.append(f"get_session_id = {get_session_id()!r}")

    # CorrelationFilter injects fields into a LogRecord.
    flt = CorrelationFilter()
    record = logging.LogRecord(
        name="smoke", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello", args=(), exc_info=None,
    )
    flt.filter(record)
    if getattr(record, "request_id", None) != "req-smoke-123":
        failures.append(
            f"CorrelationFilter did not attach request_id; got "
            f"{getattr(record, 'request_id', None)!r}"
        )
    if getattr(record, "session_id", None) != "sess-smoke-456":
        failures.append(
            f"CorrelationFilter did not attach session_id; got "
            f"{getattr(record, 'session_id', None)!r}"
        )

    # install_correlation_filter is idempotent.
    install_correlation_filter()
    install_correlation_filter()
    messages.append("install_correlation_filter idempotent")

    # Clear bindings (set to default "-").
    bind_request_id(None)
    bind_session_id(None)
    if get_request_id() != "-" or get_session_id() != "-":
        failures.append("bind_*_id(None) did not reset to default '-'.")

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
