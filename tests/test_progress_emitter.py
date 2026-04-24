"""Tests for the ProgressEmitter abstraction (MIGRATION_PLAN.md Wave 1).

Covers:
  - NoOpEmitter swallows everything (the orchestrator default)
  - SSEEmitter pushes events into the asyncio.Queue
  - SSEEmitter close() is idempotent + sentinel-bound
  - TelegramEmitter forwards `agent_complete` to streamer.mark_complete
  - TelegramEmitter ignores unknown event types (forward-compat for
    Wave 4 widening to agent_started / agent_failed / verdict / done)
  - TelegramEmitter close() flushes the streamer
  - All three implementations satisfy the runtime-checkable Protocol
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from trajectory.progress import (
    NoOpEmitter,
    ProgressEmitter,
    SSEEmitter,
    TelegramEmitter,
)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_all_emitters_satisfy_protocol():
    """Each implementation must pass the runtime-checkable Protocol so
    `isinstance(x, ProgressEmitter)` works in tests / DI containers."""
    assert isinstance(NoOpEmitter(), ProgressEmitter)
    assert isinstance(SSEEmitter(asyncio.Queue()), ProgressEmitter)
    streamer_stub = MagicMock()
    assert isinstance(TelegramEmitter(streamer_stub), ProgressEmitter)


# ---------------------------------------------------------------------------
# NoOpEmitter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_noop_emit_and_close_are_silent():
    emitter = NoOpEmitter()
    # Any event shape, any number of times, never raises and returns None.
    assert await emitter.emit({"type": "agent_complete", "agent": "x"}) is None
    assert await emitter.emit({"type": "anything", "data": [1, 2, 3]}) is None
    assert await emitter.close() is None
    # Multiple closes are fine.
    assert await emitter.close() is None


# ---------------------------------------------------------------------------
# SSEEmitter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sse_emitter_pushes_to_queue():
    queue: asyncio.Queue = asyncio.Queue()
    emitter = SSEEmitter(queue)

    await emitter.emit({"type": "agent_complete", "agent": "soc_check"})
    await emitter.emit({"type": "agent_complete", "agent": "sponsor_register"})

    e1 = await asyncio.wait_for(queue.get(), timeout=0.5)
    e2 = await asyncio.wait_for(queue.get(), timeout=0.5)
    assert e1 == {"type": "agent_complete", "agent": "soc_check"}
    assert e2 == {"type": "agent_complete", "agent": "sponsor_register"}


@pytest.mark.asyncio
async def test_sse_emitter_close_emits_done_sentinel():
    queue: asyncio.Queue = asyncio.Queue()
    emitter = SSEEmitter(queue)
    await emitter.close()

    sentinel = await asyncio.wait_for(queue.get(), timeout=0.5)
    assert sentinel == {"type": "done"}


@pytest.mark.asyncio
async def test_sse_emitter_close_is_idempotent():
    """Double-close from a misbehaving try/finally must not enqueue a
    second sentinel — the consumer would see it as a phantom event."""
    queue: asyncio.Queue = asyncio.Queue()
    emitter = SSEEmitter(queue)
    await emitter.close()
    await emitter.close()
    await emitter.close()

    # Exactly one sentinel; the next get() should time out.
    first = await asyncio.wait_for(queue.get(), timeout=0.2)
    assert first == {"type": "done"}
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_sse_emitter_emit_after_close_is_silent():
    """Once closed, late emits are dropped rather than raising — the
    orchestrator may still have an in-flight `mark()` call when the
    SSE consumer disconnects."""
    queue: asyncio.Queue = asyncio.Queue()
    emitter = SSEEmitter(queue)
    await emitter.close()

    await emitter.emit({"type": "agent_complete", "agent": "late"})

    # Only the `done` sentinel should be in the queue.
    first = await asyncio.wait_for(queue.get(), timeout=0.2)
    assert first == {"type": "done"}
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)


# ---------------------------------------------------------------------------
# TelegramEmitter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_telegram_emitter_forwards_agent_complete():
    streamer = MagicMock()
    streamer.mark_complete = AsyncMock()
    streamer.flush = AsyncMock()
    emitter = TelegramEmitter(streamer)

    await emitter.emit({"type": "agent_complete", "agent": "soc_check"})
    await emitter.emit({"type": "agent_complete", "agent": "sponsor_register"})

    assert streamer.mark_complete.await_count == 2
    streamer.mark_complete.assert_any_await("soc_check")
    streamer.mark_complete.assert_any_await("sponsor_register")


@pytest.mark.asyncio
async def test_telegram_emitter_ignores_unknown_event_types():
    """Wave 4 may add agent_started / agent_failed / verdict / done.
    None of those should reach the streamer until Telegram learns to
    render them — they're a no-op today."""
    streamer = MagicMock()
    streamer.mark_complete = AsyncMock()
    streamer.flush = AsyncMock()
    emitter = TelegramEmitter(streamer)

    await emitter.emit({"type": "agent_started", "agent": "soc_check"})
    await emitter.emit({"type": "agent_failed", "agent": "x", "error": "boom"})
    await emitter.emit({"type": "verdict", "data": {}})
    await emitter.emit({"type": "done"})
    await emitter.emit({"random": "garbage"})

    streamer.mark_complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_emitter_ignores_agent_complete_without_name():
    """Defensive: malformed event with missing or non-string agent
    name must not crash the streamer."""
    streamer = MagicMock()
    streamer.mark_complete = AsyncMock()
    streamer.flush = AsyncMock()
    emitter = TelegramEmitter(streamer)

    await emitter.emit({"type": "agent_complete"})  # no agent key
    await emitter.emit({"type": "agent_complete", "agent": None})
    await emitter.emit({"type": "agent_complete", "agent": 42})

    streamer.mark_complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_emitter_close_flushes_streamer():
    """Final flush must run so the message reflects the all-complete
    state even if the last mark fell within the debounce window."""
    streamer = MagicMock()
    streamer.flush = AsyncMock()
    emitter = TelegramEmitter(streamer)

    await emitter.close()

    streamer.flush.assert_awaited_once()
