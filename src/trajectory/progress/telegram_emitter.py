"""TelegramEmitter — wraps PhaseOneProgressStreamer.

Translates transport-agnostic progress events back into the
Telegram-specific `streamer.mark_complete(agent_name)` calls that
debounce-edit a single Telegram message. The streamer's 1.2s
debounce + RetryAfter backoff stays untouched (CLAUDE.md Rule 9
load-bearing pattern).

Only `agent_complete` events are forwarded; other event types
(`agent_started`, `agent_failed`, etc. — Wave 4) are silently
dropped. The Telegram surface only renders completions; pending
agents are derived from `all_agents - completed`.
"""

from __future__ import annotations

import logging

from ..bot.progress_stream import PhaseOneProgressStreamer

logger = logging.getLogger(__name__)


class TelegramEmitter:
    """ProgressEmitter that drives a PhaseOneProgressStreamer."""

    def __init__(self, streamer: PhaseOneProgressStreamer) -> None:
        self._streamer = streamer

    async def emit(self, event: dict) -> None:
        event_type = event.get("type")
        if event_type == "agent_complete":
            agent = event.get("agent")
            if isinstance(agent, str):
                await self._streamer.mark_complete(agent)
            else:
                logger.debug("agent_complete event without agent name: %r", event)
        # Other event types are intentional no-ops on Telegram. Adding
        # cases here is safe — see MIGRATION_PLAN.md ADR-002 consequences.

    async def close(self) -> None:
        # Final flush so the message reflects the all-complete state
        # even if the last mark fell within the debounce window.
        await self._streamer.flush()
