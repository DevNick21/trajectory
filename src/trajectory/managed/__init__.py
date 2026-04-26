"""Managed Agents integration.

Genuine `client.beta.sessions.*` usage — sibling module to `sub_agents/`
rather than nested inside it because MA sessions are not single-turn
structured-output calls and don't fit that folder's conventions.

Sessions registered post-2026-04-25 migration (PROCESS Entry 43, Workstream I):
  - company_investigator   — high-fidelity Phase 1 company research
  - reviews_investigator   — replaces no-op jobspy reviews path
  - verdict_deep_research  — gated; live-web research before issuing verdict
  - cv_tailor_advisor      — Advisor-tool-paired CV generation
  - prompt_auditor_empirical — build-time empirical injection testing

The `SESSIONS` dict is the registry `llm.call_in_session(name, ...)`
dispatches against. Concrete callers live in this package; each module
self-registers on import via `_register_session(name, fn)`.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

# name -> coroutine implementing the session. Each registered fn accepts
# whatever args/kwargs the agent caller passes through `call_in_session`.
SESSIONS: dict[str, Callable[..., Awaitable[Any]]] = {}


def _register_session(name: str, fn: Callable[..., Awaitable[Any]]) -> None:
    """Register a managed session under `name`.

    Re-registration is allowed (test isolation, hot-reload). Logs a
    warning if a name is taken.
    """
    if name in SESSIONS and SESSIONS[name] is not fn:
        import logging
        logging.getLogger(__name__).warning(
            "Managed session %r re-registered (was %r, now %r)",
            name, SESSIONS[name], fn,
        )
    SESSIONS[name] = fn


# Eager imports register the concrete sessions. Each import is guarded
# so a failure in one session module doesn't break the others — the
# top-level `llm.call_in_session` will raise NotImplementedError for an
# unregistered name with a helpful message.

def _safe_import(modpath: str) -> None:
    try:
        __import__(modpath)
    except Exception as exc:  # pragma: no cover - defensive
        import logging
        logging.getLogger(__name__).warning(
            "Managed session import failed: %s (%s)", modpath, exc,
        )


_safe_import("trajectory.managed.company_investigator")
_safe_import("trajectory.managed.reviews_investigator")
_safe_import("trajectory.managed.verdict_deep_research")
_safe_import("trajectory.managed.cv_tailor_advisor")
_safe_import("trajectory.managed.prompt_auditor_empirical")
