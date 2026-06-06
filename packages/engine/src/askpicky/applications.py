"""Local manual application tracker.

This module intentionally owns only the public-engine tracker: application rows
and user-entered statuses. It does not schedule reminders or deliver messages.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

import aiosqlite
from pydantic import BaseModel

from .parsers import analyse_job_description
from .parsers.jd_analysis import (
    ApplicationPriority,
    LocalJobAnalysis,
)
from .retrieval import EvidenceDocument, build_evidence_snapshot
from .schemas import CareerEntry
from .storage import _connect, _ensure_db, get_all_career_entries_for_user


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

ApplicationSource = Literal["forward_job", "local_jd"]


class ApplicationRecord(BaseModel):
    """The user-visible application-tracker row."""

    id: Optional[int] = None
    user_id: str
    session_id: str
    company_name: str
    role_title: str
    job_url: Optional[str] = None
    verdict_decision: Optional[str] = None
    source: ApplicationSource = "forward_job"
    raw_jd_text: Optional[str] = None
    local_analysis: Optional[LocalJobAnalysis] = None
    evidence_snapshot: Optional[LocalJobAnalysis] = None
    application_priority: Optional[ApplicationPriority] = None
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


def _analysis_to_json(analysis: LocalJobAnalysis) -> str:
    return analysis.model_dump_json()


def _parse_analysis(value: Optional[str]) -> Optional[LocalJobAnalysis]:
    if not value:
        return None
    try:
        return LocalJobAnalysis.model_validate_json(value)
    except Exception:
        return None


def _evidence_documents(entries: list[CareerEntry]) -> list[EvidenceDocument]:
    documents: list[EvidenceDocument] = []
    for entry in entries:
        structured = ""
        if entry.structured is not None:
            try:
                structured = json.dumps(entry.structured, sort_keys=True)
            except TypeError:
                structured = str(entry.structured)
        documents.append(
            EvidenceDocument(
                evidence_id=entry.entry_id,
                text=entry.raw_text,
                structured_text=structured,
            )
        )
    return documents


def _derive_company_name(jd_text: str, explicit: Optional[str] = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()[:120]
    for line in jd_text.splitlines()[:20]:
        match = re.match(r"\s*(?:company|employer|organisation|organization)\s*:\s*(.+)", line, flags=re.I)
        if match:
            candidate = match.group(1).strip(" -|\t")
            if candidate:
                return candidate[:120]
    return "Unknown company"


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
    async with await _connect() as db:
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
                verdict_decision, source, status, last_status_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'forward_job', 'forwarded', ?, ?)
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


async def create_local_application_from_jd(
    *,
    user_id: str,
    jd_text: str,
    company_name: Optional[str] = None,
) -> ApplicationRecord:
    """Save a pasted job description as a manual tracker application."""

    await _ensure_db()
    now = _now()
    analysis = analyse_job_description(jd_text)
    entries = await get_all_career_entries_for_user(user_id)
    evidence_snapshot = build_evidence_snapshot(analysis, _evidence_documents(entries))
    session_id = f"local:{uuid4().hex}"
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO application_tracker (
                user_id, session_id, company_name, role_title, job_url,
                verdict_decision, source, raw_jd_text, local_analysis_json,
                evidence_snapshot_json, application_priority, status,
                last_status_at, created_at
            ) VALUES (?, ?, ?, ?, NULL, NULL, 'local_jd', ?, ?, ?, ?, 'forwarded', ?, ?)
            """,
            (
                user_id,
                session_id,
                _derive_company_name(jd_text, company_name),
                analysis.role_title,
                jd_text.strip(),
                _analysis_to_json(analysis),
                _analysis_to_json(evidence_snapshot),
                analysis.application_priority,
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
    user_id: Optional[str] = None,
) -> Optional[ApplicationRecord]:
    """Set a tracker row's status. Returns the updated row or None."""
    await _ensure_db()
    now = _now()
    async with await _connect() as db:
        where = "WHERE session_id = ?"
        where_params: tuple[Any, ...] = (session_id,)
        if user_id is not None:
            where += " AND user_id = ?"
            where_params = (session_id, user_id)

        applied_at_clause = ""
        if new_status == "applied":
            applied_at_clause = ", applied_at = COALESCE(applied_at, ?)"
            params: tuple[Any, ...] = (
                new_status,
                _iso(now),
                notes,
                _iso(now),
                *where_params,
            )
        else:
            params = (new_status, _iso(now), notes, *where_params)
        sql = (
            "UPDATE application_tracker "
            f"SET status = ?, last_status_at = ?, notes = COALESCE(?, notes){applied_at_clause} "
            f"{where}"
        )
        await db.execute(sql, params)
        await db.commit()
        async with db.execute(
            f"SELECT id FROM application_tracker {where}",
            where_params,
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return await _fetch_application(db, row[0])


async def get_application(
    *,
    user_id: str,
    session_id: str,
) -> Optional[ApplicationRecord]:
    """Fetch one tracker row owned by a user."""

    await _ensure_db()
    async with await _connect() as db:
        record = await _fetch_application_by_session(db, user_id, session_id)
        if record is None:
            return None
        if record.source == "local_jd":
            return (await _refresh_local_evidence_snapshots(db, user_id, [record]))[0]
        return record


async def update_application_metadata(
    *,
    user_id: str,
    session_id: str,
    company_name: Optional[str] = None,
    role_title: Optional[str] = None,
    notes: Optional[str] = None,
) -> Optional[ApplicationRecord]:
    """Edit user-controlled tracker metadata."""

    await _ensure_db()
    now = _now()
    async with await _connect() as db:
        await db.execute(
            """
            UPDATE application_tracker
            SET company_name = COALESCE(?, company_name),
                role_title = COALESCE(?, role_title),
                notes = COALESCE(?, notes),
                last_status_at = ?
            WHERE session_id = ? AND user_id = ?
            """,
            (
                company_name.strip()[:120] if company_name and company_name.strip() else None,
                role_title.strip()[:160] if role_title and role_title.strip() else None,
                notes.strip()[:2000] if notes is not None else None,
                _iso(now),
                session_id,
                user_id,
            ),
        )
        await db.commit()
        record = await _fetch_application_by_session(db, user_id, session_id)
        if record is None:
            return None
        if record.source == "local_jd":
            return (await _refresh_local_evidence_snapshots(db, user_id, [record]))[0]
        return record


async def refresh_application_evidence(
    *,
    user_id: str,
    session_id: str,
) -> Optional[ApplicationRecord]:
    """Force-refresh a saved application's local evidence snapshot."""

    await _ensure_db()
    async with await _connect() as db:
        record = await _fetch_application_by_session(db, user_id, session_id)
        if record is None:
            return None
        if record.source != "local_jd":
            return record
        return (await _refresh_local_evidence_snapshots(db, user_id, [record]))[0]


async def delete_application(
    *,
    user_id: str,
    session_id: str,
) -> bool:
    """Delete one manual tracker row owned by the current user."""

    await _ensure_db()
    async with await _connect() as db:
        cur = await db.execute(
            "DELETE FROM application_tracker WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def list_applications(
    *,
    user_id: str,
    status_in: Optional[list[ApplicationStatus]] = None,
    limit: int = 100,
) -> list[ApplicationRecord]:
    """List a user's applications, newest first."""
    await _ensure_db()
    async with await _connect() as db:
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
        records = [await _fetch_application(db, i) for i in ids]
        if any(record.source == "local_jd" for record in records):
            records = await _refresh_local_evidence_snapshots(db, user_id, records)
        return records


async def _fetch_application_by_session(
    db: aiosqlite.Connection,
    user_id: str,
    session_id: str,
) -> Optional[ApplicationRecord]:
    async with db.execute(
        "SELECT id FROM application_tracker WHERE session_id = ? AND user_id = ?",
        (session_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return await _fetch_application(db, row[0])


async def _refresh_local_evidence_snapshots(
    db: aiosqlite.Connection,
    user_id: str,
    records: list[ApplicationRecord],
) -> list[ApplicationRecord]:
    entries = await get_all_career_entries_for_user(user_id)
    documents = _evidence_documents(entries)
    refreshed_records: list[ApplicationRecord] = []
    changed = False

    for record in records:
        if record.source != "local_jd":
            refreshed_records.append(record)
            continue
        base_analysis = record.local_analysis
        if base_analysis is None and record.raw_jd_text:
            base_analysis = analyse_job_description(record.raw_jd_text)
        if base_analysis is None:
            refreshed_records.append(record)
            continue

        snapshot = build_evidence_snapshot(base_analysis, documents)
        old_payload = (
            record.evidence_snapshot.model_dump(mode="json")
            if record.evidence_snapshot is not None
            else None
        )
        new_payload = snapshot.model_dump(mode="json")
        updated = record.model_copy(deep=True)
        updated.evidence_snapshot = snapshot
        updated.application_priority = snapshot.application_priority
        refreshed_records.append(updated)
        if old_payload != new_payload:
            changed = True
            await db.execute(
                """
                UPDATE application_tracker
                SET evidence_snapshot_json = ?, application_priority = ?
                WHERE id = ?
                """,
                (
                    _analysis_to_json(snapshot),
                    snapshot.application_priority,
                    record.id,
                ),
            )

    if changed:
        await db.commit()
    return refreshed_records


async def _fetch_application(
    db: aiosqlite.Connection,
    row_id: int,
) -> ApplicationRecord:
    async with db.execute(
        """
        SELECT id, user_id, session_id, company_name, role_title, job_url,
               verdict_decision, source, raw_jd_text, local_analysis_json,
               evidence_snapshot_json, application_priority, status, applied_at,
               last_status_at, notes, created_at
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
        source=row[7] or "forward_job",
        raw_jd_text=row[8],
        local_analysis=_parse_analysis(row[9]),
        evidence_snapshot=_parse_analysis(row[10]),
        application_priority=row[11],
        status=row[12],
        applied_at=_parse_dt(row[13]),
        last_status_at=_parse_dt(row[14]) or _now(),
        notes=row[15],
        created_at=_parse_dt(row[16]) or _now(),
    )
