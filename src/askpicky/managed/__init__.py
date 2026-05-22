"""Managed Agents integration.

Genuine `client.beta.sessions.*` usage — sibling module to `sub_agents/`
rather than nested inside it because MA sessions are not single-turn
structured-output calls and don't fit that folder's conventions.

Sessions registered (post-2026-05-22 overhaul, ASKPICKY.md §10):
  - company_investigator   — high-fidelity Phase 1 company research
  - reviews_investigator   — Glassdoor mirrors / archive / Reddit aggregation
  - verdict_deep_research  — premium "Real-time hiring intent verification"
  - cover_letter_session   — managed Phase 4 cover letter (live web fetch)
  - likely_questions_session — managed interview-questions (live web)
  - salary_strategist_session — managed salary strategist (Code Execution)
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


_safe_import("askpicky.managed.company_investigator")
_safe_import("askpicky.managed.reviews_investigator")
_safe_import("askpicky.managed.verdict_deep_research")
_safe_import("askpicky.managed.prompt_auditor_empirical")
# Managed agentic Phase 4 generators.
_safe_import("askpicky.managed.cover_letter_session")
_safe_import("askpicky.managed.likely_questions_session")
_safe_import("askpicky.managed.salary_strategist_session")
