"""Cross-cutting observability: structured log fields + per-stage timing.

D1 + D2. The primary export is `install_correlation_filter()` which
attaches a `logging.Filter` that injects `request_id` and `session_id`
from contextvars into every log record. The context is set at the
request boundary (bot on_message, FastAPI middleware) and
contextvars propagate naturally through asyncio.gather.
"""

from .logging_context import (
    CorrelationFilter,
    bind_request_id,
    bind_session_id,
    get_request_id,
    get_session_id,
    install_correlation_filter,
    new_request_id,
)

__all__ = [
    "CorrelationFilter",
    "bind_request_id",
    "bind_session_id",
    "get_request_id",
    "get_session_id",
    "install_correlation_filter",
    "new_request_id",
]
