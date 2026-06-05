"""Local manual application tracker.

This module intentionally owns only the public-engine tracker: application rows
and user-entered statuses. It does not schedule reminders or deliver messages.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

import aiosqlite
from pydantic import BaseModel

from .config import settings
from .storage import _ensure_db


ApplicationStatus = Literal[
    "forwarded",
    "applied",
    "no_response",
    "rejected_screen",
    "rejected_interview",
    "rejected_offer",
    "offer_received",
    "offer_accepted",
    "offer_declined",
]


class ApplicationRecord(BaseModel):
    """The user-visible application-tracker row."""

    id: Optional[int] = None
    user_id: str
    session_id: str
    company_name: str
    role_title: str
    job_url: Optional[str] = None
    verdict_decision: Optional[str] = None
    status: ApplicationStatus = "forwarded"
    applied_at: Optional[datetime] = None
    last_status_at: datetime
    notes: Optional[str] = None
    created_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def create_application_record(
    *,
    user_id: str,
    session_id: str,
    company_name: str,
    role_title: str,
    job_url: Optional[str] = None,
    verdict_decision: Optional[str] = None,
) -> ApplicationRecord:
    """Insert a tracker row for a fresh forward-job session.

    Idempotent on `session_id`: if one exists, return it unchanged.
    """
    await _ensure_db()
    now = _now()
    async with aiosqlite.connect(settings.sqlite_db_path) as db:
        async with db.execute(
            "SELECT id FROM application_tracker WHERE session_id = ?",
            (session_id,),
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            return await _fetch_application(db, existing[0])
        await db.execute(
            """
            INSERT INTO application_tracker (
                user_id, session_id, company_name, role_title, job_url,
                verdict_decision, status, last_status_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'forwarded', ?, ?)
            """,
            (
                user_id,
                session_id,
                company_name,
                role_title,
                job_url,
                verdict_decision,
                _iso(now),
                _iso(now),
            ),
        )
        await db.commit()
        async with db.execute(
            "SELECT id FROM application_tracker WHERE session_id = ?",
            (session_id,),
        ) as cur:
            row = await cur.fetchone()
        return await _fetch_application(db, row[0])


async def update_application_status(
    *,
    session_id: str,
    new_status: ApplicationStatus,
    notes: Optional[str] = None,
) -> Optional[ApplicationRecord]:
    """Set a tracker row's status. Returns the updated row or None."""
    await _ensure_db()
    now = _now()
    async with aiosqlite.connect(settings.sqlite_db_path) as db:
        applied_at_clause = ""
        if new_status == "applied":
            applied_at_clause = ", applied_at = COALESCE(applied_at, ?)"
            params: tuple[Any, ...] = (
                new_status,
                _iso(now),
                notes,
                _iso(now),
                session_id,
            )
        else:
            params = (new_status, _iso(now), notes, session_id)
        sql = (
            "UPDATE application_tracker "
            f"SET status = ?, last_status_at = ?, notes = COALESCE(?, notes){applied_at_clause} "
            "WHERE session_id = ?"
        )
        await db.execute(sql, params)
        await db.commit()
        async with db.execute(
            "SELECT id FROM application_tracker WHERE session_id = ?",
            (session_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return await _fetch_application(db, row[0])


async def list_applications(
    *,
    user_id: str,
    status_in: Optional[list[ApplicationStatus]] = None,
    limit: int = 100,
) -> list[ApplicationRecord]:
    """List a user's applications, newest first."""
    await _ensure_db()
    async with aiosqlite.connect(settings.sqlite_db_path) as db:
        if status_in:
            placeholders = ",".join("?" * len(status_in))
            sql = (
                "SELECT id FROM application_tracker "
                f"WHERE user_id = ? AND status IN ({placeholders}) "
                "ORDER BY last_status_at DESC LIMIT ?"
            )
            params: tuple[Any, ...] = (user_id, *status_in, limit)
        else:
            sql = (
                "SELECT id FROM application_tracker "
                "WHERE user_id = ? ORDER BY last_status_at DESC LIMIT ?"
            )
            params = (user_id, limit)
        async with db.execute(sql, params) as cur:
            ids = [r[0] for r in await cur.fetchall()]
        return [await _fetch_application(db, i) for i in ids]


async def _fetch_application(
    db: aiosqlite.Connection,
    row_id: int,
) -> ApplicationRecord:
    async with db.execute(
        """
        SELECT id, user_id, session_id, company_name, role_title, job_url,
               verdict_decision, status, applied_at, last_status_at, notes,
               created_at
        FROM application_tracker WHERE id = ?
        """,
        (row_id,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise ValueError(f"application_tracker id={row_id} disappeared mid-read")
    return ApplicationRecord(
        id=row[0],
        user_id=row[1],
        session_id=row[2],
        company_name=row[3],
        role_title=row[4],
        job_url=row[5],
        verdict_decision=row[6],
        status=row[7],
        applied_at=_parse_dt(row[8]),
        last_status_at=_parse_dt(row[9]) or _now(),
        notes=row[10],
        created_at=_parse_dt(row[11]) or _now(),
    )
