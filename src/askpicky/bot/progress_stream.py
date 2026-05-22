"""Phase 1 progress streamer.

Edits a single Telegram message to show which of the 8 Phase 1 sub-agents
have completed, in near-real-time. Respects Telegram's ~1 edit/second rate
limit by debouncing to at most one edit every 1.2 seconds.

Usage in orchestrator.handle_forward_job:

    msg = await context.bot.send_message(chat_id, "Running checks...")
    streamer = PhaseOneProgressStreamer(
        bot=context.bot,
        chat_id=chat_id,
        message_id=msg.message_id,
        all_agents=PHASE_1_AGENT_NAMES,
    )
    tasks = {asyncio.create_task(agent_fn()): name for name, agent_fn in ...}
    for coro in asyncio.as_completed(list(tasks)):
        name = tasks[coro]          # resolve task -> name before awaiting
        await coro
        await streamer.mark_complete(name)
    await streamer.flush()

See bot/formatting.py:format_phase1_progress for the rendered text.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from telegram import Bot
from telegram.error import RetryAfter, TimedOut

logger = logging.getLogger(__name__)


class PhaseOneProgressStreamer:
    """Streams Phase 1 sub-agent completion via debounced Telegram message edits."""

    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        message_id: int,
        all_agents: list[str],
        debounce_seconds: float = 1.2,
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._message_id = message_id
        self._all_agents = list(all_agents)
        self._debounce = debounce_seconds
        self._completed: list[str] = []
        self._last_edit_at: float = 0.0
        self._pending_edit: bool = False
        self._lock = asyncio.Lock()

    async def mark_complete(self, agent_name: str) -> None:
        """Record an agent as done and schedule a debounced edit."""
        async with self._lock:
            if agent_name not in self._completed:
                self._completed.append(agent_name)
            now = time.monotonic()
            if now - self._last_edit_at >= self._debounce:
                await self._do_edit()
            else:
                self._pending_edit = True

    async def flush(self) -> None:
        """Force a final edit showing all-complete state."""
        async with self._lock:
            await self._do_edit()

    async def _do_edit(self) -> None:
        """Must be called under self._lock."""
        from .formatting import format_phase1_progress

        text = format_phase1_progress(
            completed_agents=list(self._completed),
            all_agents=self._all_agents,
        )
        await self._edit_with_backoff(text)
        self._last_edit_at = time.monotonic()
        self._pending_edit = False

    async def _edit_with_backoff(self, text: str) -> None:
        for attempt in range(3):
            try:
                await self._bot.edit_message_text(
                    chat_id=self._chat_id,
                    message_id=self._message_id,
                    text=text,
                    parse_mode="HTML",
                )
                return
            except RetryAfter as e:
                wait = float(e.retry_after) + 0.1
                logger.debug("Telegram RetryAfter %ss on progress edit; waiting.", wait)
                await asyncio.sleep(wait)
            except TimedOut:
                logger.debug("Telegram TimedOut on progress edit (attempt %d).", attempt)
                await asyncio.sleep(1.0)
            except Exception as e:
                # Non-retryable (e.g. message deleted) — swallow so the
                # pipeline doesn't die over a cosmetic update.
                logger.warning("Progress edit failed (non-retryable): %s", e)
                return
