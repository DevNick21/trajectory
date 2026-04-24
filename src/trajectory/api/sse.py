"""SSE event-stream helper.

Drains an `asyncio.Queue` of progress events and yields each as an
sse-starlette frame. Stops on a `done` or `error` event. The runner
task that fills the queue is owned by the caller; this helper only
drains.

Disconnect handling: when the client closes the EventSource, the
generator's `__anext__` is cancelled, the `finally` block runs, and
the caller's runner task is cancelled (see `event_stream_with_runner`
in routes/sessions.py).
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator


_TERMINAL_EVENT_TYPES = ("done", "error")


async def event_stream(queue: asyncio.Queue) -> AsyncIterator[dict]:
    """Yield queue events as sse-starlette frames until a terminal event.

    Each frame is `{"data": "<json>"}` — sse-starlette wraps it in a
    `data: <json>\\n\\n` SSE message. `default=str` lets datetimes
    serialise without per-event coercion at the call site.
    """
    while True:
        event = await queue.get()
        yield {"data": json.dumps(event, default=str)}
        if event.get("type") in _TERMINAL_EVENT_TYPES:
            break
