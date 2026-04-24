"""Transport-agnostic progress emitters for Phase 1 streaming.

The orchestrator emits structured events (`{"type": "agent_complete",
"agent": <name>}`); each surface (Telegram, web SSE, CLI) provides an
emitter implementation that translates those events to its native
delivery channel. See MIGRATION_PLAN.md ADR-002.
"""

from .emitter import NoOpEmitter, ProgressEmitter
from .sse_emitter import SSEEmitter

__all__ = ["NoOpEmitter", "ProgressEmitter", "SSEEmitter", "TelegramEmitter"]


def __getattr__(name: str):
    # Lazy import — TelegramEmitter pulls python-telegram-bot, which the
    # FastAPI surface doesn't need at import time.
    if name == "TelegramEmitter":
        from .telegram_emitter import TelegramEmitter
        return TelegramEmitter
    raise AttributeError(f"module 'trajectory.progress' has no attribute {name!r}")
