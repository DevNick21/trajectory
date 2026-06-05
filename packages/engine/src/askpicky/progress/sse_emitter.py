"""SSEEmitter — pushes progress events into an asyncio.Queue.

The FastAPI handler (Wave 4) reads from the same queue and serialises
each event to a `data: <json>\\n\\n` SSE frame. See MIGRATION_PLAN.md
§3 architecture.

`close()` is idempotent: subsequent calls do not enqueue duplicate
sentinels, so accidental double-close in `try/finally` blocks is
harmless.
"""

from __future__ import annotations

import asyncio


class SSEEmitter:
    """ProgressEmitter that pushes events to an asyncio.Queue."""

    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue = queue
        self._closed = False

    async def emit(self, event: dict) -> None:
        if self._closed:
            return
        await self._queue.put(event)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # Sentinel so the consumer iterator can break cleanly.
        await self._queue.put({"type": "done"})
