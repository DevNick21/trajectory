"""Memory recall — read side of the cross-application learning loop.

`recall()` reads from the SQLite cross_app_memory table populated by
`recorder.py`. Used directly by salary_strategist, draft_reply, and
likely_questions (they call recall() to produce a context string the
agent prompt embeds).
"""

from __future__ import annotations

import json
import logging
from typing import Literal, Optional

import aiosqlite

from ..config import settings

logger = logging.getLogger(__name__)


# MEMORY_TOOL_DEFINITION lived here as a client-tool registration for
# agents that want tool-use-driven recall. salary_strategist /
# draft_reply / likely_questions all pre-fetch via `recall()` and
# inject the results into the prompt instead, so no agent ever needs
# to dispatch the tool. Removed 2026-04-26 in the dead-code sweep —
# recover via `git log` when a tool-use call site materialises.


async def recall(
    *,
    user_id: str,
    query: str = "",
    kind: Optional[Literal[
        "application_outcome",
        "recruiter_interaction",
        "negotiation_result",
    ]] = None,
    limit: int = 5,
) -> list[dict]:
    """Recall relevant memories.

    `query` is currently unused (substring filtering is a follow-up);
    the SQL filter is on (user_id, kind) ordered by created_at DESC.
    """
    limit = max(1, min(int(limit), 20))
    sql = (
        "SELECT kind, payload, created_at FROM cross_app_memory "
        "WHERE user_id = ?"
    )
    args: tuple = (user_id,)
    if kind:
        sql += " AND kind = ?"
        args = (user_id, kind)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args = (*args, limit)

    try:
        async with aiosqlite.connect(settings.sqlite_db_path) as db:
            async with db.execute(sql, args) as cur:
                rows = await cur.fetchall()
    except Exception as exc:  # pragma: no cover - table may not exist yet
        logger.info("memory.recall: empty (table not initialised: %s)", exc)
        return []

    out: list[dict] = []
    for row in rows:
        kind_v, payload, created = row
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            data = {"_raw": payload}
        out.append({
            "kind": kind_v,
            "created_at": created,
            **data,
        })
    return out


async def recall_as_text(*, user_id: str, kind: Optional[str] = None,
                         limit: int = 5) -> str:
    """Convenience: format `recall()` output as a short prose digest
    suitable for embedding directly in an agent's user_input."""
    entries = await recall(user_id=user_id, kind=kind, limit=limit)  # type: ignore[arg-type]
    if not entries:
        return "[no prior cross-application history for this user]"
    lines = [
        f"({e['created_at'][:10]} {e['kind']}) "
        f"{json.dumps({k: v for k, v in e.items() if k not in {'kind', 'created_at'}}, default=str)[:200]}"
        for e in entries
    ]
    return "\n".join(lines)
