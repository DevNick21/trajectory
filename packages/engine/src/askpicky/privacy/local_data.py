"""Local export and hard-delete primitives for the public SQLite data model."""

from __future__ import annotations

from typing import Any, Optional

from askpicky_privacy import USER_SCOPED_TABLES, redact_export_rows

from ..storage import _connect


async def _rows_for_user(table: str, user_id_col: Optional[str], user_id: str) -> list[dict[str, Any]]:
    async with await _connect() as db:
        if user_id_col is None:
            async with db.execute(
                "SELECT * FROM llm_cost_log WHERE session_id IN "
                "(SELECT session_id FROM sessions WHERE user_id = ?) "
                "ORDER BY created_at DESC",
                (user_id,),
            ) as cur:
                rows = await cur.fetchall()
                columns = [item[0] for item in cur.description or []]
        else:
            async with db.execute(
                f"SELECT * FROM {table} WHERE {user_id_col} = ?",
                (user_id,),
            ) as cur:
                rows = await cur.fetchall()
                columns = [item[0] for item in cur.description or []]
    return [dict(zip(columns, row)) for row in rows]


async def export_user_data(*, user_id: str, include_raw: bool = True) -> dict[str, Any]:
    """Export all local rows scoped to a user."""

    export: dict[str, Any] = {}
    for table, user_id_col in USER_SCOPED_TABLES.items():
        rows = await _rows_for_user(table, user_id_col, user_id)
        if not include_raw:
            rows = redact_export_rows(table=table, rows=rows)
        export[table] = rows

    async with await _connect() as db:
        async with db.execute(
            """
            SELECT * FROM session_progress_events
            WHERE session_id IN (SELECT session_id FROM sessions WHERE user_id = ?)
            ORDER BY id ASC
            """,
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()
            columns = [item[0] for item in cur.description or []]
    export["session_progress_events"] = [dict(zip(columns, row)) for row in rows]
    return export


async def hard_delete_user_data(*, user_id: str) -> dict[str, int]:
    """Hard-delete all local rows scoped to a user."""

    deleted: dict[str, int] = {}
    async with await _connect() as db:
        async with db.execute(
            "SELECT session_id FROM sessions WHERE user_id = ?",
            (user_id,),
        ) as cur:
            session_ids = [row[0] for row in await cur.fetchall()]

        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            for table in ("session_progress_events", "llm_cost_log"):
                cur = await db.execute(
                    f"DELETE FROM {table} WHERE session_id IN ({placeholders})",
                    tuple(session_ids),
                )
                deleted[table] = cur.rowcount if cur.rowcount is not None else 0

        for table, user_id_col in USER_SCOPED_TABLES.items():
            if user_id_col is None:
                continue
            cur = await db.execute(
                f"DELETE FROM {table} WHERE {user_id_col} = ?",
                (user_id,),
            )
            deleted[table] = cur.rowcount if cur.rowcount is not None else 0
        await db.commit()
    return deleted


async def delete_cv_data(*, user_id: str) -> int:
    """Delete CV-derived career entries for a user."""

    async with await _connect() as db:
        cur = await db.execute(
            "DELETE FROM career_entries WHERE user_id = ? AND kind = 'cv_bullet'",
            (user_id,),
        )
        await db.commit()
        return cur.rowcount if cur.rowcount is not None else 0


async def delete_application_data(*, user_id: str, session_id: str) -> dict[str, int]:
    """Delete one application/session and related local traces."""

    deleted: dict[str, int] = {}
    async with await _connect() as db:
        for table in ("application_tracker", "application_assist_sessions", "answer_attempts"):
            cur = await db.execute(
                f"DELETE FROM {table} WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
            deleted[table] = cur.rowcount if cur.rowcount is not None else 0
        for table in ("session_progress_events", "llm_cost_log"):
            cur = await db.execute(
                f"DELETE FROM {table} WHERE session_id = ?",
                (session_id,),
            )
            deleted[table] = cur.rowcount if cur.rowcount is not None else 0
        cur = await db.execute(
            "DELETE FROM sessions WHERE user_id = ? AND session_id = ?",
            (user_id, session_id),
        )
        deleted["sessions"] = cur.rowcount if cur.rowcount is not None else 0
        await db.commit()
    return deleted
