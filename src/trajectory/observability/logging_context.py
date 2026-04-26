"""Correlation IDs threaded through async context.

The filter appends `request_id` and `session_id` to every log record.
Set the context at the request boundary:

    from trajectory.observability import bind_request_id, new_request_id
    bind_request_id(new_request_id())

Both fields default to "-" so formatters that expect the attribute
always find it, even on records emitted outside any request scope
(startup, background workers).
"""

from __future__ import annotations

import contextvars
import logging
import uuid
from typing import Optional


_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trajectory_request_id", default="-"
)
_session_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trajectory_session_id", default="-"
)


def new_request_id() -> str:
    """Return a short opaque id suitable for log correlation + URLs."""
    return uuid.uuid4().hex[:12]


def bind_request_id(request_id: Optional[str]) -> contextvars.Token:
    """Set the current request_id; returns a token for restoration."""
    return _request_id_var.set(request_id or "-")


def bind_session_id(session_id: Optional[str]) -> contextvars.Token:
    return _session_id_var.set(session_id or "-")


def get_request_id() -> str:
    return _request_id_var.get()


def get_session_id() -> str:
    return _session_id_var.get()


class CorrelationFilter(logging.Filter):
    """Attach request_id + session_id to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        # setattr rather than record.__dict__ so formatters using
        # %(request_id)s pick it up uniformly across LoggerAdapter etc.
        if not hasattr(record, "request_id"):
            record.request_id = _request_id_var.get()
        if not hasattr(record, "session_id"):
            record.session_id = _session_id_var.get()
        return True


_installed = False


def install_correlation_filter() -> None:
    """Attach CorrelationFilter to the root logger. Idempotent.

    Safe to call from multiple entry points (bot app, FastAPI lifespan,
    standalone scripts). Second and subsequent calls are no-ops.
    """
    global _installed
    if _installed:
        return
    root = logging.getLogger()
    flt = CorrelationFilter()
    root.addFilter(flt)
    for handler in root.handlers:
        handler.addFilter(flt)
    _installed = True
