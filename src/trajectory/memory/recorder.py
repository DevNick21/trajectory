"""Memory recorders — write side of the cross-application learning loop.

Persists structured cross-application events to the local SQLite DB
(table `cross_app_memory`). Reads happen via `recall.py` and via the
client-side memory tool registered with agents that need recall.

Design choice: we do NOT use `beta.memory_stores` here because that
surface is scoped to a single Managed Agents *session* — it doesn't
persist across conversations. Cross-application learning needs
durable, queryable storage; SQLite is the right primitive.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import aiosqlite

from ..config import settings

logger = logging.getLogger(__name__)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cross_app_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_user_kind
    ON cross_app_memory(user_id, kind, created_at DESC);
"""


_initialised = False


async def _ensure_table() -> None:
    global _initialised
    if _initialised:
        return
    async with aiosqlite.connect(settings.sqlite_db_path) as db:
        await db.executescript(_SCHEMA_SQL)
        await db.commit()
    _initialised = True


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


async def _record(user_id: str, kind: str, payload: dict) -> None:
    """Internal: write one memory entry. Best-effort; logs on failure."""
    try:
        await _ensure_table()
        async with aiosqlite.connect(settings.sqlite_db_path) as db:
            await db.execute(
                "INSERT INTO cross_app_memory (user_id, kind, payload, created_at) "
                "VALUES (?, ?, ?, ?)",
                (user_id, kind, json.dumps(payload, default=str), _now_iso()),
            )
            await db.commit()
        logger.info("memory.record kind=%s user=%s ok", kind, user_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Memory record failed (kind=%s): %s", kind, exc)


async def record_application_outcome(
    *,
    user_id: str,
    session_id: str,
    company_name: str,
    role_title: str,
    outcome: Literal[
        "applied",
        "no_response",
        "rejected_screen",
        "rejected_interview",
        "rejected_offer",
        "offer_received",
        "offer_accepted",
        "offer_declined",
    ],
    notes: Optional[str] = None,
) -> None:
    """Record the terminal outcome of an application."""
    await _record(user_id, "application_outcome", {
        "session_id": session_id,
        "company_name": company_name,
        "role_title": role_title,
        "outcome": outcome,
        "notes": notes or "",
        "at": _now_iso(),
    })


async def record_recruiter_interaction(
    *,
    user_id: str,
    session_id: Optional[str],
    interaction_type: Literal[
        "initial_outreach",
        "phone_screen",
        "salary_inquiry",
        "offer_negotiation",
        "decline",
    ],
    user_response_summary: str,
    recruiter_followup: Optional[str] = None,
) -> None:
    """Record what the user said + how the recruiter responded."""
    await _record(user_id, "recruiter_interaction", {
        "session_id": session_id,
        "interaction_type": interaction_type,
        "user_response_summary": user_response_summary,
        "recruiter_followup": recruiter_followup or "",
        "at": _now_iso(),
    })


async def record_negotiation_result(
    *,
    user_id: str,
    session_id: str,
    company_name: str,
    role_title: str,
    asked_gbp: int,
    offered_gbp: int,
    final_gbp: Optional[int],
    accepted: bool,
    notes: Optional[str] = None,
) -> None:
    """Record a salary negotiation: asked vs offered vs accepted."""
    await _record(user_id, "negotiation_result", {
        "session_id": session_id,
        "company_name": company_name,
        "role_title": role_title,
        "asked_gbp": asked_gbp,
        "offered_gbp": offered_gbp,
        "final_gbp": final_gbp,
        "accepted": accepted,
        "notes": notes or "",
        "at": _now_iso(),
    })
