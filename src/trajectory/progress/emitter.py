"""ProgressEmitter Protocol — the contract every transport satisfies.

Orchestrator code only knows this Protocol; it doesn't import Telegram,
FastAPI, or anything transport-shaped. New surfaces (Slack, Discord,
CLI) only need a new emitter (~50 lines) — the orchestrator is
untouched.

Event shape (current Wave 1 contract):

    {"type": "agent_complete", "agent": "<agent_name>"}

Wave 4 may widen this to include `agent_started`, `agent_failed`,
`verdict`, `done` etc. when the SSE API surface starts consuming
richer events. Adding new event types is non-breaking — emitters
that don't care about a type ignore it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ProgressEmitter(Protocol):
    """Any transport that wants Phase 1 progress events."""

    async def emit(self, event: dict) -> None: ...
    async def close(self) -> None: ...


class NoOpEmitter:
    """Default when no surface is attached (CLI runs, unit tests,
    orchestrator invocations from the FastAPI app before its SSE
    queue is wired)."""

    async def emit(self, event: dict) -> None:
        return None

    async def close(self) -> None:
        return None
