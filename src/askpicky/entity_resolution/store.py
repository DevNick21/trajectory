"""SQLite-backed cache for resolved company identities.

Cache key is the identity_id (preferred: `crn:12345678`; fallback:
`name:<slug>`). Lookups go through `find_by_crn` / `find_by_slug`
first, then the resolver only re-runs on miss.

Cached rows are kept for `IDENTITY_TTL_DAYS` — long enough to survive
a typical job-search session, short enough that company-status drift
(dissolution, sponsor licence change) shows up within a fortnight.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite

from ..config import settings
from ..storage import _ensure_db
from .schemas import CompanyIdentity, ResolutionTrace

logger = logging.getLogger(__name__)


IDENTITY_TTL_DAYS = 14


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


def _row_to_identity(row: tuple) -> CompanyIdentity:
    (
        identity_id, canonical_name, aliases, legal_names, trading_names,
        crn, company_status, sponsor_register_name, sponsor_status,
        sponsor_match_confidence, parent_crn, domain, confidence,
        sources, trace_json, resolved_at,
    ) = row
    trace = None
    if trace_json:
        try:
            trace = ResolutionTrace.model_validate_json(trace_json)
        except Exception:
            trace = None
    return CompanyIdentity(
        identity_id=identity_id,
        canonical_name=canonical_name,
        aliases=json.loads(aliases or "[]"),
        legal_names=json.loads(legal_names or "[]"),
        trading_names=json.loads(trading_names or "[]"),
        crn=crn,
        company_status=company_status,
        sponsor_register_name=sponsor_register_name,
        sponsor_status=sponsor_status,
        sponsor_match_confidence=sponsor_match_confidence,
        parent_crn=parent_crn,
        domain=domain,
        confidence=confidence or 0.0,
        sources=json.loads(sources or "[]"),
        trace=trace,
        resolved_at=_parse_dt(resolved_at) or _now(),
    )


_SELECT_COLS = (
    "identity_id, canonical_name, aliases, legal_names, trading_names, "
    "crn, company_status, sponsor_register_name, sponsor_status, "
    "sponsor_match_confidence, parent_crn, domain, confidence, "
    "sources, trace_json, resolved_at"
)


async def find_by_crn(crn: str) -> Optional[CompanyIdentity]:
    await _ensure_db()
    async with aiosqlite.connect(settings.sqlite_db_path) as db:
        async with db.execute(
            f"SELECT {_SELECT_COLS} FROM company_identities WHERE crn = ?",
            (crn,),
        ) as cur:
            row = await cur.fetchone()
    return _row_to_identity(row) if row else None


async def find_by_identity_id(identity_id: str) -> Optional[CompanyIdentity]:
    await _ensure_db()
    async with aiosqlite.connect(settings.sqlite_db_path) as db:
        async with db.execute(
            f"SELECT {_SELECT_COLS} FROM company_identities WHERE identity_id = ?",
            (identity_id,),
        ) as cur:
            row = await cur.fetchone()
    return _row_to_identity(row) if row else None


async def find_by_alias(alias: str) -> Optional[CompanyIdentity]:
    """Look up by an exact alias match in the JSON aliases array.

    SQLite's json_each lets us treat the JSON list as a virtual table
    of strings; the trade-off vs a separate `company_aliases` table is
    that we keep one row per identity instead of N. For our scale
    (10s-1000s of identities per single-user deploy) the inline scan
    is fine. Move to a separate table when this becomes the hot path.
    """
    await _ensure_db()
    async with aiosqlite.connect(settings.sqlite_db_path) as db:
        async with db.execute(
            f"""
            SELECT {_SELECT_COLS} FROM company_identities
            WHERE EXISTS (
                SELECT 1 FROM json_each(company_identities.aliases) AS j
                WHERE j.value = ?
            ) LIMIT 1
            """,
            (alias,),
        ) as cur:
            row = await cur.fetchone()
    return _row_to_identity(row) if row else None


async def upsert_identity(identity: CompanyIdentity) -> None:
    await _ensure_db()
    async with aiosqlite.connect(settings.sqlite_db_path) as db:
        trace_json = identity.trace.model_dump_json() if identity.trace else None
        await db.execute(
            """
            INSERT INTO company_identities (
                identity_id, canonical_name, aliases, legal_names, trading_names,
                crn, company_status, sponsor_register_name, sponsor_status,
                sponsor_match_confidence, parent_crn, domain, confidence,
                sources, trace_json, resolved_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(identity_id) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                aliases = excluded.aliases,
                legal_names = excluded.legal_names,
                trading_names = excluded.trading_names,
                crn = excluded.crn,
                company_status = excluded.company_status,
                sponsor_register_name = excluded.sponsor_register_name,
                sponsor_status = excluded.sponsor_status,
                sponsor_match_confidence = excluded.sponsor_match_confidence,
                parent_crn = excluded.parent_crn,
                domain = excluded.domain,
                confidence = excluded.confidence,
                sources = excluded.sources,
                trace_json = excluded.trace_json,
                resolved_at = excluded.resolved_at
            """,
            (
                identity.identity_id,
                identity.canonical_name,
                json.dumps(identity.aliases),
                json.dumps(identity.legal_names),
                json.dumps(identity.trading_names),
                identity.crn,
                identity.company_status,
                identity.sponsor_register_name,
                identity.sponsor_status,
                identity.sponsor_match_confidence,
                identity.parent_crn,
                identity.domain,
                identity.confidence,
                json.dumps(identity.sources),
                trace_json,
                _iso(identity.resolved_at),
            ),
        )
        await db.commit()


def is_stale(identity: CompanyIdentity, *, now: Optional[datetime] = None) -> bool:
    now = now or _now()
    return now - identity.resolved_at > timedelta(days=IDENTITY_TTL_DAYS)
