"""Transport-agnostic progress emitters for Phase 1 streaming.

The orchestrator emits structured events (`{"type": "agent_complete",
"agent": <name>}`); each surface (web SSE, CLI) provides an emitter
implementation that translates those events to its native delivery
channel.
"""

from .emitter import NoOpEmitter, ProgressEmitter
from .sse_emitter import SSEEmitter

__all__ = ["NoOpEmitter", "ProgressEmitter", "SSEEmitter"]
