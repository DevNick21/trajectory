"""Bot conversation compaction + context editing helpers.

PROCESS Entry 43, Workstream H.

The Telegram bot runs as one long-lived conversation per user. Without
intervention, the system prompt + per-user prefix + onboarding history
+ all subsequent intents pile up into one ever-growing context. Today's
workaround: persist only structured CareerEntries; drop everything else.

With Anthropic's Compaction + Context editing features, we can keep the
full conversation thread and let the platform manage it server-side:
  - Compaction summarises old turns once context approaches the window.
  - Context editing prunes tool-result blocks that are no longer
    relevant.

These are opt-in (config flags) until verified live against multi-day
threads.
"""

from __future__ import annotations

from typing import Any

from ..config import settings


def compaction_kwargs(*, scope: str = "bot_user") -> dict[str, Any]:
    """Return the `messages.create` kwargs that enable Compaction +
    Context editing for the current bot conversation, IF the relevant
    config flags are on.

    `scope` lets us evolve different policies per surface (bot per-user
    threads vs. ephemeral API session) without changing call sites.

    Empty dict when both flags are off — caller can splat unconditionally
    via `**compaction_kwargs()` and the call shape is unchanged.
    """
    out: dict[str, Any] = {}

    if settings.enable_bot_compaction:
        # Tracks the platform's `compaction` field shape. Default
        # "auto" — the API decides when to summarise.
        out["compaction"] = {"strategy": "auto"}

    if settings.enable_bot_context_editing:
        # Default: clear tool_result blocks once the conversation is
        # approaching the window. Other strategies live behind config
        # if we need finer control.
        out["context_management"] = {
            "edits": [{"type": "clear_tool_uses_20250919"}]
        }

    return out
