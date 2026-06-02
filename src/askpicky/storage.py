"""Persistence: SQLite for structured state, FAISS for career-entry retrieval.

Skeleton notes:
- All SQL is hand-written against `aiosqlite`; no SQLAlchemy ORM layer yet.
- The FAISS index is kept in-memory and flushed to `settings.faiss_index_path`
  on every insert. `sentence-transformers` is imported lazily so importing
  this module stays cheap.
- Costs for each LLM call land in `llm_cost_log`. `total_cost_usd()` is the
  one authoritative read used by `llm.py` before every non-CRITICAL call.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from .config import settings


def _utcnow() -> datetime:
    """Naive UTC timestamp — drop-in replacement for the deprecated
    `datetime.utcnow()`, behaviourally identical. Kept naive to stay
    compatible with already-stored isoformat strings without timezone
    suffix.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


from .schemas import (
    AdviceSnippet,
    AnswerAttempt,
    ApplicationAssistSession,
    CareerEntry,
    ExperienceAtom,
    MemoryEdge,
    MemoryReviewStatus,
    MemorySuggestion,
    QuestionType,
    QueuedJob,
    Session,
    StoryFrame,
    UserProfile,
    WritingStyleProfile,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS career_entries (
    entry_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_career_entries_user ON career_entries(user_id);

CREATE TABLE IF NOT EXISTS writing_style_profiles (
    profile_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_style_user ON writing_style_profiles(user_id);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    intent TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS session_progress_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_progress_session
    ON session_progress_events(session_id, id);

CREATE TABLE IF NOT EXISTS scraped_pages (
    url TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_cost_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    agent_name TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    created_at TEXT NOT NULL,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cost_agent ON llm_cost_log(agent_name);

CREATE TABLE IF NOT EXISTS quota_usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    category TEXT NOT NULL,
    period TEXT NOT NULL,
    units INTEGER NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quota_user_period
    ON quota_usage_events(user_id, category, period);

CREATE TABLE IF NOT EXISTS security_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    event_type TEXT NOT NULL,
    resource_type TEXT,
    resource_id TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_security_audit_user_time
    ON security_audit_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_audit_event_time
    ON security_audit_events(event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS extension_pairing_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_extension_pairing_user
    ON extension_pairing_tokens(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS queued_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    job_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    session_id TEXT,
    error TEXT,
    added_at TEXT NOT NULL,
    processed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_queued_user ON queued_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_queued_status ON queued_jobs(status);

CREATE TABLE IF NOT EXISTS jobs (
    -- A persistent Job entity. Each forwarded URL creates or reuses one;
    -- sessions reference job_id so the app can disambiguate "draft a CV
    -- for that role" by title + company.
    job_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    role_title TEXT NOT NULL,
    company_name TEXT NOT NULL,
    company_domain TEXT,
    last_seen_url TEXT,
    last_seen_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_user_seen
    ON jobs(user_id, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_user_company_role
    ON jobs(user_id, company_name, role_title);

CREATE TABLE IF NOT EXISTS application_tracker (
    -- The user-visible "what's happening with my applications" surface
    -- (ASKPICKY.md Layer 5: personal tracker + Layer 6: outcome feed
    -- into the network). 1:1 with the source forward_job session.
    -- Status moves through: forwarded -> applied -> {no_response,
    -- rejected_screen, rejected_interview, rejected_offer,
    -- offer_received -> {offer_accepted, offer_declined}}.
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL UNIQUE,
    company_name TEXT NOT NULL,
    role_title TEXT NOT NULL,
    job_url TEXT,
    verdict_decision TEXT,
    status TEXT NOT NULL DEFAULT 'forwarded',
    applied_at TEXT,
    last_status_at TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracker_user_status
    ON application_tracker(user_id, status, last_status_at DESC);
CREATE INDEX IF NOT EXISTS idx_tracker_session
    ON application_tracker(session_id);

CREATE TABLE IF NOT EXISTS company_identities (
    -- Unified company identity cache (entity_resolution/). identity_id
    -- is `crn:{number}` when a Companies House registration was anchored,
    -- otherwise `name:{slug}`. Downstream lookups (sponsor_register,
    -- companies_house, the front-page sponsor-search tool) all share
    -- the same identity row instead of independently fuzzy-matching.
    identity_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    legal_names TEXT NOT NULL DEFAULT '[]',
    trading_names TEXT NOT NULL DEFAULT '[]',
    crn TEXT,
    company_status TEXT,
    sponsor_register_name TEXT,
    sponsor_status TEXT,
    sponsor_match_confidence REAL,
    parent_crn TEXT,
    domain TEXT,
    confidence REAL NOT NULL DEFAULT 0,
    sources TEXT NOT NULL DEFAULT '[]',
    trace_json TEXT,
    resolved_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_company_id_crn
    ON company_identities(crn);
CREATE INDEX IF NOT EXISTS idx_company_id_canonical
    ON company_identities(canonical_name);
CREATE INDEX IF NOT EXISTS idx_company_id_domain
    ON company_identities(domain);

CREATE TABLE IF NOT EXISTS notifications (
    -- Cross-surface notification + nudge queue. The scheduler picks
    -- rows where status='pending' AND scheduled_for <= now() and
    -- dispatches each via the channel-specific notifier. Web reads
    -- this table directly via the API; Email is push.
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    channel TEXT NOT NULL,
    payload TEXT NOT NULL,
    scheduled_for TEXT NOT NULL,
    sent_at TEXT,
    read_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notif_due
    ON notifications(scheduled_for, status);
CREATE INDEX IF NOT EXISTS idx_notif_user_status
    ON notifications(user_id, status, channel, created_at DESC);

CREATE TABLE IF NOT EXISTS application_assist_sessions (
    assist_session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT,
    job_id TEXT,
    company_name TEXT,
    role_title TEXT,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assist_sessions_user
    ON application_assist_sessions(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS answer_attempts (
    attempt_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    assist_session_id TEXT,
    session_id TEXT,
    question_type TEXT NOT NULL,
    visibility TEXT NOT NULL,
    save_status TEXT NOT NULL,
    raw_retention_until TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_answer_attempts_user
    ON answer_attempts(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_answer_attempts_assist
    ON answer_attempts(assist_session_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS experience_atoms (
    atom_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    atom_type TEXT NOT NULL,
    text TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT,
    visibility TEXT NOT NULL,
    review_status TEXT NOT NULL,
    sensitive INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_atoms_user_status
    ON experience_atoms(user_id, review_status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_atoms_user_type
    ON experience_atoms(user_id, atom_type);

CREATE TABLE IF NOT EXISTS story_frames (
    story_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    visibility TEXT NOT NULL,
    review_status TEXT NOT NULL,
    sensitive INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_story_frames_user_status
    ON story_frames(user_id, review_status, updated_at DESC);

CREATE TABLE IF NOT EXISTS memory_edges (
    edge_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_edges_source
    ON memory_edges(user_id, source_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_memory_edges_target
    ON memory_edges(user_id, target_id, edge_type);

CREATE TABLE IF NOT EXISTS advice_snippets (
    advice_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    topic_tags TEXT NOT NULL DEFAULT '[]',
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_advice_source
    ON advice_snippets(source_type);
"""


# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------


_init_lock = asyncio.Lock()
_initialised = False


async def _ensure_db() -> None:
    """Create the DB file and tables if they don't exist. Idempotent.

    journal_mode=WAL is a file-level pragma that persists in the SQLite
    header once set; subsequent connections inherit it. We set it here
    (plus synchronous=NORMAL, the recommended safety/perf pairing for
    WAL) so concurrent writers from the FastAPI + test harness
    don't serialise on a single rollback-journal writer.

    After the schema script runs, we apply additive ALTER TABLE
    migrations defensively (IF NOT EXISTS isn't supported for columns
    in SQLite < 3.35 and we want to run on DBs created before the
    column existed). Errors are swallowed when the column is already
    present — that's the expected path on an up-to-date DB.
    """
    global _initialised
    if _initialised:
        return
    async with _init_lock:
        if _initialised:
            return
        settings.sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(settings.sqlite_db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=NORMAL")
            await db.executescript(_SCHEMA_SQL)
            await _apply_additive_migrations(db)
            await db.commit()
        _initialised = True


_ADDITIVE_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    # (table, column, DDL fragment). One-directional: add-only, never
    # drops or renames. See B1/B2 plan: cache token columns were added
    # to `llm_cost_log` after the table was created in some dev DBs.
    (
        "llm_cost_log",
        "cache_read_tokens",
        "ALTER TABLE llm_cost_log ADD COLUMN "
        "cache_read_tokens INTEGER NOT NULL DEFAULT 0",
    ),
    (
        "llm_cost_log",
        "cache_creation_tokens",
        "ALTER TABLE llm_cost_log ADD COLUMN "
        "cache_creation_tokens INTEGER NOT NULL DEFAULT 0",
    ),
]


async def _apply_additive_migrations(db: Any) -> None:
    """Apply add-only column migrations idempotently.

    SQLite ALTER TABLE ADD COLUMN raises OperationalError when the
    column already exists — catching that is how we get idempotency
    without maintaining a version table.
    """
    for table, column, ddl in _ADDITIVE_COLUMN_MIGRATIONS:
        async with db.execute(f"PRAGMA table_info({table})") as cur:
            cols = [row[1] async for row in cur]
        if column in cols:
            continue
        try:
            await db.execute(ddl)
        except Exception as exc:  # pragma: no cover — race/duplicate
            # Swallow only "duplicate column" / "already exists"; surface
            # anything else so real schema breakage isn't silenced.
            if "duplicate column" in str(exc).lower() or "already exists" in str(exc).lower():
                continue
            raise


async def _connect() -> _ConnectionWithPragmas:
    """Return an un-awaited aiosqlite Connection proxy.

    Every caller uses `async with await _connect() as db:`. aiosqlite ≥0.21
    starts the worker thread on the first `await` and treats a second
    `__aenter__` as a repeat start, raising "threads can only be started
    once". Returning the connection WITHOUT awaiting it lets the caller
    both await and enter the context exactly once.

    `busy_timeout` is per-connection and must be re-applied each time.
    5s matches SQLite's undocumented default but makes it explicit.
    """
    await _ensure_db()
    conn = aiosqlite.connect(settings.sqlite_db_path)

    async def _connect_with_pragmas() -> Any:
        db = await conn
        await db.execute("PRAGMA busy_timeout=5000")
        return db

    # Wrap so that the caller's `async with await _connect()` picks up
    # the busy_timeout before the first query. aiosqlite's Connection
    # is an async context manager that returns itself on __aenter__,
    # so we need a thin shim that applies the pragma on open.
    return _ConnectionWithPragmas(settings.sqlite_db_path)


class _ConnectionWithPragmas:
    """Wraps aiosqlite.connect to apply per-connection pragmas on open."""

    def __init__(self, path: Any) -> None:
        self._path = path
        self._inner = None

    def __await__(self):
        return self._open().__await__()

    async def _open(self) -> Any:
        self._inner = await aiosqlite.connect(self._path)
        await self._inner.execute("PRAGMA busy_timeout=5000")
        return self._inner

    async def __aenter__(self):
        if self._inner is None:
            await self._open()
        return self._inner

    async def __aexit__(self, exc_type, exc, tb):
        if self._inner is not None:
            await self._inner.close()
            self._inner = None


def _dumps(model_obj: Any) -> str:
    if hasattr(model_obj, "model_dump_json"):
        return model_obj.model_dump_json()
    return json.dumps(model_obj, default=str)


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------


async def get_user_profile(user_id: str) -> Optional[UserProfile]:
    async with await _connect() as db:
        async with db.execute(
            "SELECT payload FROM user_profiles WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return UserProfile.model_validate_json(row[0])


async def upsert_user_profile(profile: UserProfile) -> None:
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO user_profiles (user_id, payload, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (profile.user_id, profile.model_dump_json(), _utcnow().isoformat()),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Career entries + FAISS retrieval
# ---------------------------------------------------------------------------


_embedding_model = None
_embedding_lock = threading.Lock()

_faiss_index = None
_faiss_id_map: list[str] = []
_faiss_lock = threading.Lock()


def _get_embedding_model() -> Any:
    global _embedding_model
    if _embedding_model is None:
        with _embedding_lock:
            if _embedding_model is None:
                from sentence_transformers import SentenceTransformer

                _embedding_model = SentenceTransformer(settings.embedding_model_name)
    return _embedding_model


def _faiss() -> tuple:
    global _faiss_index, _faiss_id_map
    if _faiss_index is not None:
        return _faiss_index, _faiss_id_map

    with _faiss_lock:
        if _faiss_index is not None:
            return _faiss_index, _faiss_id_map

        import faiss

        path = settings.faiss_index_path
        id_map_path = Path(str(path) + ".ids.json")
        if path.exists() and id_map_path.exists():
            _faiss_index = faiss.read_index(str(path))
            _faiss_id_map = json.loads(id_map_path.read_text())
        else:
            _faiss_index = faiss.IndexFlatIP(settings.embedding_dim)
            _faiss_id_map = []
    return _faiss_index, _faiss_id_map


def _faiss_save_sync() -> None:
    """Actual disk write — blocks, keep off the event loop."""
    import faiss

    path = settings.faiss_index_path
    path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(_faiss_index, str(path))
    Path(str(path) + ".ids.json").write_text(json.dumps(_faiss_id_map))


async def _faiss_save() -> None:
    """C4: runs `_faiss_save_sync` on a worker thread.

    Without this, every `insert_career_entry` blocks the loop on the
    index write — noticeable under the Phase 1 fan-out when multiple
    agents return results concurrently. Matches the pattern already
    used by `_embed`.
    """
    await asyncio.to_thread(_faiss_save_sync)


async def _embed(text: str) -> list[float]:
    """Synchronously embed on a worker thread to avoid blocking the loop."""
    model = _get_embedding_model()
    return await asyncio.to_thread(
        lambda: model.encode([text], normalize_embeddings=True)[0].tolist()
    )


async def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Encode multiple texts in a single model forward pass.

    SentenceTransformer is 8-20x faster encoding a batch of N texts than
    N individual calls — the transformer backbone caches the tokenisation
    and matrix multiplies across the batch dimension. For typical
    onboarding payloads (10-30 short career entries) the wall-clock
    difference is ~300ms vs ~3s.
    """
    if not texts:
        return []
    model = _get_embedding_model()
    # With 1 text, fall through to the single path to avoid overhead.
    if len(texts) == 1:
        return [await _embed(texts[0])]
    return await asyncio.to_thread(
        lambda: model.encode(texts, normalize_embeddings=True).tolist()
    )


async def insert_career_entries_batch(entries: list[CareerEntry]) -> None:
    """Insert multiple career entries with batched embedding.

    Computes embeddings for all entries whose `embedding` field is None
    in a single model call, then inserts into SQLite + FAISS.
    """
    if not entries:
        return
    import numpy as np

    to_embed = [
        (i, e) for i, e in enumerate(entries) if e.embedding is None
    ]
    if to_embed:
        idxs, batch = zip(*to_embed)
        embeddings = await _embed_batch([e.raw_text for e in batch])
        for idx, emb in zip(idxs, embeddings):
            entries[idx].embedding = emb

    from faiss import normalize_L2

    index, id_map = _faiss()
    with _faiss_lock:
        new_vecs = np.asarray([e.embedding for e in entries], dtype="float32")
        normalize_L2(new_vecs)
        index.add(new_vecs)
        for e in entries:
            id_map.append(e.entry_id)
    await _faiss_save()

    sql = """
        INSERT INTO career_entries
            (entry_id, user_id, kind, raw_text, payload, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(entry_id) DO UPDATE SET
            payload = excluded.payload
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    async with await _connect() as db:
        for entry in entries:
            await db.execute(
                sql,
                (
                    entry.entry_id,
                    entry.user_id,
                    entry.kind,
                    entry.raw_text,
                    entry.model_dump_json(),
                    entry.created_at.isoformat() if entry.created_at else now_iso,
                ),
            )
        await db.commit()

    logger.debug(
        "insert_career_entries_batch: %d entries written to FAISS + SQLite",
        len(entries),
    )


async def insert_career_entry(entry: CareerEntry) -> None:
    import numpy as np

    if entry.embedding is None:
        entry.embedding = await _embed(entry.raw_text)

    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO career_entries
                (entry_id, user_id, kind, raw_text, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(entry_id) DO UPDATE SET
                payload = excluded.payload
            """,
            (
                entry.entry_id,
                entry.user_id,
                entry.kind,
                entry.raw_text,
                entry.model_dump_json(),
                entry.created_at.isoformat(),
            ),
        )
        await db.commit()

    index, id_map = _faiss()
    vec = np.asarray([entry.embedding], dtype="float32")
    with _faiss_lock:
        index.add(vec)
        id_map.append(entry.entry_id)
    # Release the threading.Lock before the to_thread hop — the save
    # doesn't need it (write is reading module-level state once) and
    # holding it across an await is a liveness hazard.
    await _faiss_save()


# Kinds that represent user-validated "master stories" — polished STAR
# narratives and Q&A answers already verified by the user in dialogue.
# Generators prefer these over raw cv_bullet / project_note because
# they sound like the user and have been pre-reviewed. See #2 in the
# "money no object" roadmap (retrieval weighting, not schema change).
STAR_BOOST_KINDS: dict[str, float] = {
    "star_polish": 1.5,
    "qa_answer": 1.2,
}


async def retrieve_relevant_entries(
    user_id: str,
    query_text: str,
    k: int = 12,
    kind_weights: Optional[dict[str, float]] = None,
) -> list[CareerEntry]:
    """FAISS nearest-neighbour over career entries for this user.

    When `kind_weights` is provided, each FAISS inner-product score is
    multiplied by the kind's weight (default 1.0 for unlisted kinds)
    and results are re-sorted. Used by Phase 4 generators to prefer
    `star_polish` + `qa_answer` entries — the "master story bank" —
    over raw cv_bullet / project_note material.

    Without weights: behaviour is identical to pre-weighting —
    FAISS-hit order is preserved.

    We over-fetch from FAISS and filter by user in Python — acceptable
    for single-user demo scale. For multi-user at scale, partition by
    user_id.
    """
    import numpy as np

    index, id_map = _faiss()
    if index.ntotal == 0 or not id_map:
        return []

    query_vec = np.asarray([await _embed(query_text)], dtype="float32")
    over_fetch = min(index.ntotal, max(k * 4, 32))
    scores, idxs = index.search(query_vec, over_fetch)

    # Keep (faiss_position, score, entry_id) so we can re-rank by
    # score × kind_weight when weights are supplied.
    def _hits_from_search(limit: int) -> list[tuple[int, float, str]]:
        search_scores, search_idxs = index.search(query_vec, limit)
        found: list[tuple[int, float, str]] = []
        for pos, (i, score) in enumerate(zip(search_idxs[0], search_scores[0])):
            if 0 <= i < len(id_map):
                found.append((pos, float(score), id_map[i]))
        return found

    hits = [
        (pos, float(score), id_map[i])
        for pos, (i, score) in enumerate(zip(idxs[0], scores[0]))
        if 0 <= i < len(id_map)
    ]
    if not hits:
        return []

    async def _entries_for_hits(
        candidate_hits: list[tuple[int, float, str]]
    ) -> dict[str, CareerEntry]:
        hit_ids = [eid for (_, _, eid) in candidate_hits]
        if not hit_ids:
            return {}
        placeholders = ",".join("?" for _ in hit_ids)
        async with await _connect() as db:
            async with db.execute(
                f"""
                SELECT payload FROM career_entries
                WHERE user_id = ? AND entry_id IN ({placeholders})
                """,
                (user_id, *hit_ids),
            ) as cur:
                rows = await cur.fetchall()

        entries: dict[str, CareerEntry] = {}
        for r in rows:
            entry = CareerEntry.model_validate_json(r[0])
            entries[entry.entry_id] = entry
        return entries

    by_id = await _entries_for_hits(hits)
    if not by_id and over_fetch < index.ntotal:
        # Local SQLite/FAISS keeps one process-wide index and filters by
        # user_id after vector search. In multi-user smoke/dev fixtures, a
        # user's entries may not appear in the first global top-N even though
        # ownership filtering is correct. Hosted pgvector should partition by
        # user_id; local mode falls back to the full index only on an empty
        # same-user first pass.
        hits = _hits_from_search(index.ntotal)
        by_id = await _entries_for_hits(hits)
        if not by_id:
            return []

    # Re-rank. Without weights, FAISS order is preserved by using the
    # original position as the sort key. With weights, multiply score
    # by kind weight and sort descending — ties break on FAISS order.
    scored: list[tuple[float, int, CareerEntry]] = []
    for (pos, score, eid) in hits:
        entry = by_id.get(eid)
        if entry is None:
            continue
        if kind_weights:
            weight = kind_weights.get(entry.kind, 1.0)
            boosted = score * weight
            scored.append((-boosted, pos, entry))
        else:
            # Pure FAISS order — use position as the primary key so
            # the numeric score doesn't matter (IndexFlatIP returns
            # higher = better; negating keeps the sort stable + correct).
            scored.append((float(pos), pos, entry))

    scored.sort(key=lambda x: (x[0], x[1]))
    return [entry for (_, _, entry) in scored[:k]]


async def search_career_entries_semantic(
    user_id: str,
    query: str,
    kind_filter: str = "ANY",
    top_k: int = 5,
    kind_weights: Optional[dict[str, float]] = None,
) -> list[CareerEntry]:
    """Kind-filterable semantic search over a user's career entries.

    Used by the agentic CV tailor's `search_career_entries` tool. Wraps
    `retrieve_relevant_entries` and applies a Python-side kind filter
    after the FAISS hop.

    `kind_filter`:
      - "ANY" → no filter
      - any literal `CareerEntry.kind` value → restrict to that kind
        (`cv_bullet`, `qa_answer`, `star_polish`, `project_note`,
        `preference`, `motivation`, `deal_breaker`, `writing_sample`,
        `conversation`)
    `kind_weights`: forwarded to `retrieve_relevant_entries` so the
    agent's retrieval prefers validated narratives (see
    `STAR_BOOST_KINDS`). Pass None for pure similarity order.
    """
    top_k = max(1, min(int(top_k), 10))
    over_fetch = top_k * 4 if kind_filter != "ANY" else top_k
    entries = await retrieve_relevant_entries(
        user_id=user_id, query_text=query, k=over_fetch,
        kind_weights=kind_weights,
    )
    if kind_filter != "ANY":
        entries = [e for e in entries if e.kind == kind_filter]
    return entries[:top_k]


async def career_entries_exist(entry_ids: list[str]) -> set[str]:
    """Used by the citation validator: returns the subset that exists."""
    if not entry_ids:
        return set()
    placeholders = ",".join("?" for _ in entry_ids)
    async with await _connect() as db:
        async with db.execute(
            f"SELECT entry_id FROM career_entries WHERE entry_id IN ({placeholders})",
            tuple(entry_ids),
        ) as cur:
            rows = await cur.fetchall()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# Writing style profiles
# ---------------------------------------------------------------------------


async def get_writing_style_profile(
    user_id: str,
) -> Optional[WritingStyleProfile]:
    async with await _connect() as db:
        async with db.execute(
            """
            SELECT payload FROM writing_style_profiles
            WHERE user_id = ?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return WritingStyleProfile.model_validate_json(row[0])


async def upsert_writing_style_profile(profile: WritingStyleProfile) -> None:
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO writing_style_profiles (profile_id, user_id, payload, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (
                profile.profile_id,
                profile.user_id,
                profile.model_dump_json(),
                _utcnow().isoformat(),
            ),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


async def insert_session(session: Session) -> None:
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO sessions (session_id, user_id, intent, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                session.user_id,
                session.intent,
                session.model_dump_json(),
                session.created_at.isoformat(),
            ),
        )
        await db.commit()


async def get_session(session_id: str) -> Optional[Session]:
    async with await _connect() as db:
        async with db.execute(
            "SELECT payload FROM sessions WHERE session_id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return Session.model_validate_json(row[0])


async def update_session(session: Session) -> None:
    async with await _connect() as db:
        await db.execute(
            "UPDATE sessions SET payload = ? WHERE session_id = ?",
            (session.model_dump_json(), session.session_id),
        )
        await db.commit()


async def get_recent_sessions(user_id: str, n: int = 5) -> list[Session]:
    async with await _connect() as db:
        async with db.execute(
            """
            SELECT payload FROM sessions
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, n),
        ) as cur:
            rows = await cur.fetchall()
    return [Session.model_validate_json(r[0]) for r in rows]


async def append_session_progress_event(session_id: str, event: dict[str, Any]) -> None:
    payload = json.dumps(event, default=str)
    event_type = str(event.get("type") or "unknown")
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO session_progress_events
                (session_id, event_type, payload, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, event_type, payload, _utcnow().isoformat()),
        )
        await db.commit()


async def get_session_progress_events(session_id: str) -> list[dict[str, Any]]:
    async with await _connect() as db:
        async with db.execute(
            """
            SELECT id, payload, created_at
            FROM session_progress_events
            WHERE session_id = ?
            ORDER BY id ASC
            """,
            (session_id,),
        ) as cur:
            rows = await cur.fetchall()

    events: list[dict[str, Any]] = []
    for event_id, payload, created_at in rows:
        try:
            event = json.loads(payload)
        except Exception:
            continue
        if isinstance(event, dict):
            event.setdefault("created_at", created_at)
            event.setdefault("event_id", event_id)
            events.append(event)
    return events


# ---------------------------------------------------------------------------
# Scraped page cache
# ---------------------------------------------------------------------------


async def cache_scraped_page(url: str, text: str, fetched_at: datetime) -> None:
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO scraped_pages (url, text, fetched_at)
            VALUES (?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                text = excluded.text,
                fetched_at = excluded.fetched_at
            """,
            (url, text, fetched_at.isoformat()),
        )
        await db.commit()


async def get_cached_page(url: str, max_age_hours: int = 24) -> Optional[str]:
    cutoff = _utcnow() - timedelta(hours=max_age_hours)
    async with await _connect() as db:
        async with db.execute(
            "SELECT text, fetched_at FROM scraped_pages WHERE url = ?",
            (url,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    fetched = datetime.fromisoformat(row[1])
    if fetched < cutoff:
        return None
    return row[0]


# ---------------------------------------------------------------------------
# LLM cost accounting
# ---------------------------------------------------------------------------


# Approximate $/token prices (verify before production). These feed
# `estimate_cost_usd` to populate `llm_cost_log.cost_usd` at every
# `log_llm_cost(...)` call. Hosted V2 reconciles actual usage through
# the quota ledger; this local estimate is for dev budgets and smoke
# rollups.
_PRICING_LAST_VERIFIED = "2026-06-01"
_PRICING_USD_PER_MTOK = {
    # DeepSeek (May 2026 — 75% promo active through 2026-05-31)
    # Post-promo: flash $0.14/$0.28, pro $1.74/$3.48
    "deepseek-flash": {"input": 0.14, "output": 0.28},
    "deepseek-pro":   {"input": 0.435, "output": 0.87},   # 75%-off promo
    # OpenAI
    "gpt-5-mini":  {"input": 0.75, "output":  4.50},
    "gpt-5":       {"input": 2.50, "output": 15.00},
    "gpt-5.5":     {"input": 5.00, "output": 30.00},
    "gpt-4o":      {"input": 2.50, "output": 10.0},
    # Cohere — REMOVED (dead code, no integration). See Process Entry 44.
}


def _price_bucket(model: str) -> dict[str, float]:
    m = model.lower()
    # DeepSeek family
    if "deepseek" in m:
        if "pro" in m:
            return _PRICING_USD_PER_MTOK["deepseek-pro"]
        return _PRICING_USD_PER_MTOK["deepseek-flash"]
    # OpenAI family
    if "gpt-5.5" in m:
        return _PRICING_USD_PER_MTOK["gpt-5.5"]
    if "gpt-5" in m or "gpt5" in m:
        if "mini" in m:
            return _PRICING_USD_PER_MTOK["gpt-5-mini"]
        return _PRICING_USD_PER_MTOK["gpt-5"]
    if "gpt-4o" in m or "gpt4o" in m:
        return _PRICING_USD_PER_MTOK["gpt-4o"]
    # Unknown — use GPT-5 pricing as a conservative default. Better to
    # overestimate than have an unknown-priced call sneak under the
    # credit-budget refusal.
    return _PRICING_USD_PER_MTOK["gpt-5"]


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    """Estimate model usage cost.

    - cache_creation_tokens: estimated at 1.25x the base input rate.
    - cache_read_tokens: estimated at 0.1x the base input rate.
    - regular input_tokens: full input rate.

    `input_tokens` from the API is the "fresh input" count — cache reads
    and cache creations are reported separately on the `usage` object
    and are NOT double-counted in input_tokens. Pricing sums all three.
    """
    p = _price_bucket(model)
    fresh_input_cost = input_tokens * p["input"]
    cache_read_cost = cache_read_tokens * p["input"] * 0.1
    cache_creation_cost = cache_creation_tokens * p["input"] * 1.25
    output_cost = output_tokens * p["output"]
    return (
        fresh_input_cost + cache_read_cost + cache_creation_cost + output_cost
    ) / 1_000_000


async def log_llm_cost(
    session_id: Optional[str],
    agent_name: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> None:
    cost = estimate_cost_usd(
        model,
        input_tokens,
        output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
    )
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO llm_cost_log
                (session_id, agent_name, model,
                 input_tokens, output_tokens, cost_usd, created_at,
                 cache_read_tokens, cache_creation_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                agent_name,
                model,
                input_tokens,
                output_tokens,
                cost,
                _utcnow().isoformat(),
                cache_read_tokens,
                cache_creation_tokens,
            ),
        )
        await db.commit()


async def total_cost_usd() -> float:
    async with await _connect() as db:
        async with db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_cost_log") as cur:
            row = await cur.fetchone()
    return float(row[0]) if row else 0.0


def _quota_limit_for(category: str) -> int:
    if category == "forward_job":
        return settings.quota_forward_job_monthly
    if category == "generator":
        return settings.quota_generator_monthly
    if category == "assist":
        return settings.quota_assist_monthly
    if category == "firecrawl":
        return settings.quota_firecrawl_monthly
    return settings.quota_chitchat_monthly


def _quota_period(now: Optional[datetime] = None) -> str:
    now = now or _utcnow()
    return f"{now.year:04d}-{now.month:02d}"


async def record_quota_usage(
    *,
    user_id: str,
    category: str,
    units: int = 1,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Atomically record quota usage if the user's monthly bucket permits it."""
    category = category or "chitchat"
    units = max(1, int(units))
    limit = _quota_limit_for(category)
    period = _quota_period()
    async with await _connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute(
            """
            SELECT COALESCE(SUM(units), 0)
            FROM quota_usage_events
            WHERE user_id = ? AND category = ? AND period = ?
            """,
            (user_id, category, period),
        ) as cur:
            row = await cur.fetchone()
        used = int(row[0] or 0) if row else 0
        if used + units > limit:
            await db.rollback()
            return {
                "allowed": False,
                "user_id": user_id,
                "category": category,
                "period": period,
                "limit": limit,
                "used": used,
            }
        await db.execute(
            """
            INSERT INTO quota_usage_events
                (user_id, category, period, units, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                category,
                period,
                units,
                json.dumps(metadata or {}, default=str),
                _utcnow().isoformat(),
            ),
        )
        await db.commit()
    return {
        "allowed": True,
        "user_id": user_id,
        "category": category,
        "period": period,
        "limit": limit,
        "used": used + units,
    }


async def append_security_audit_event(
    *,
    event_type: str,
    user_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO security_audit_events
                (user_id, event_type, resource_type, resource_id, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                event_type,
                resource_type,
                resource_id,
                json.dumps(payload or {}, default=str),
                _utcnow().isoformat(),
            ),
        )
        await db.commit()


def _hash_extension_pairing_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_extension_pairing_token(
    *,
    user_id: str,
    ttl_minutes: int = 10,
) -> dict[str, Any]:
    """Create a one-time extension pairing token for an authenticated user.

    The hosted web app requests this after Supabase sign-in, then the Chrome
    companion exchanges the token plus the current Supabase access token. The
    API stores only a hash and consumes the token on first exchange.
    """
    token = secrets.token_urlsafe(32)
    now = _utcnow()
    expires_at = now + timedelta(minutes=max(1, int(ttl_minutes)))
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO extension_pairing_tokens
                (token_hash, user_id, expires_at, consumed_at, created_at)
            VALUES (?, ?, ?, NULL, ?)
            """,
            (
                _hash_extension_pairing_token(token),
                user_id,
                expires_at.isoformat(),
                now.isoformat(),
            ),
        )
        await db.commit()
    return {"token": token, "expires_at": expires_at}


async def consume_extension_pairing_token(token: str) -> Optional[dict[str, Any]]:
    """Consume and return a valid extension pairing token, if present."""
    token_hash = _hash_extension_pairing_token(token.strip())
    now = _utcnow()
    async with await _connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute(
            """
            SELECT user_id, expires_at, consumed_at
            FROM extension_pairing_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            await db.rollback()
            return None

        user_id, expires_at_raw, consumed_at = row
        try:
            expires_at = datetime.fromisoformat(expires_at_raw)
        except ValueError:
            await db.rollback()
            return None
        if consumed_at or expires_at <= now:
            await db.rollback()
            return None

        await db.execute(
            """
            UPDATE extension_pairing_tokens
            SET consumed_at = ?
            WHERE token_hash = ?
            """,
            (now.isoformat(), token_hash),
        )
        await db.commit()
    return {"user_id": user_id, "expires_at": expires_at}


async def session_cost_summary(session_id: str) -> dict:
    """Return total + per-agent cost for a single session.

    Shape: {"total_usd": float, "by_agent": {agent_name: total_usd, ...}}.
    Empty session (no logged calls) returns total=0.0, by_agent={}.
    Used by the GET /api/sessions/{id} response to render the cost
    breakdown (MIGRATION_PLAN.md Wave 3 / Wave 8).
    """
    async with await _connect() as db:
        async with db.execute(
            """
            SELECT agent_name, SUM(cost_usd)
            FROM llm_cost_log
            WHERE session_id = ?
            GROUP BY agent_name
            """,
            (session_id,),
        ) as cur:
            rows = await cur.fetchall()
    by_agent = {row[0]: float(row[1]) for row in rows}
    return {"total_usd": sum(by_agent.values()), "by_agent": by_agent}


# ---------------------------------------------------------------------------
# Queued jobs (batch processing — see api/routes/queue.py)
# ---------------------------------------------------------------------------


def _queued_from_row(row) -> QueuedJob:
    """Shared row→model conversion used by every queue query."""
    (qid, user_id, job_url, status, session_id, error, added_at,
     processed_at) = row
    return QueuedJob(
        id=qid,
        user_id=user_id,
        job_url=job_url,
        status=status,
        session_id=session_id,
        error=error,
        added_at=datetime.fromisoformat(added_at),
        processed_at=(
            datetime.fromisoformat(processed_at) if processed_at else None
        ),
    )


async def insert_queued_job(user_id: str, job_url: str) -> QueuedJob:
    import uuid

    job = QueuedJob(
        id=str(uuid.uuid4()),
        user_id=user_id,
        job_url=job_url,
        status="pending",
        added_at=_utcnow(),
    )
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO queued_jobs
                (id, user_id, job_url, status, added_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (job.id, user_id, job_url, job.added_at.isoformat()),
        )
        await db.commit()
    return job


async def list_queued_jobs(
    user_id: str, status_filter: Optional[str] = None,
) -> list[QueuedJob]:
    sql = (
        "SELECT id, user_id, job_url, status, session_id, error, added_at, "
        "processed_at FROM queued_jobs WHERE user_id = ?"
    )
    args: tuple = (user_id,)
    if status_filter:
        sql += " AND status = ?"
        args = (user_id, status_filter)
    sql += " ORDER BY added_at DESC"
    async with await _connect() as db:
        async with db.execute(sql, args) as cur:
            rows = await cur.fetchall()
    return [_queued_from_row(r) for r in rows]


async def get_queued_job(job_id: str) -> Optional[QueuedJob]:
    async with await _connect() as db:
        async with db.execute(
            "SELECT id, user_id, job_url, status, session_id, error, "
            "added_at, processed_at FROM queued_jobs WHERE id = ?",
            (job_id,),
        ) as cur:
            row = await cur.fetchone()
    return _queued_from_row(row) if row else None


async def _update_queued_job_status(
    job_id: str,
    status: str,
    *,
    session_id: Optional[str] = None,
    error: Optional[str] = None,
    mark_processed: bool = False,
) -> None:
    now = _utcnow().isoformat() if mark_processed else None
    async with await _connect() as db:
        await db.execute(
            """
            UPDATE queued_jobs
            SET status = ?,
                session_id = COALESCE(?, session_id),
                error = COALESCE(?, error),
                processed_at = COALESCE(?, processed_at)
            WHERE id = ?
            """,
            (status, session_id, error, now, job_id),
        )
        await db.commit()


async def mark_queued_job_processing(job_id: str) -> None:
    await _update_queued_job_status(job_id, "processing")


async def mark_queued_job_done(job_id: str, session_id: str) -> None:
    await _update_queued_job_status(
        job_id, "done", session_id=session_id, mark_processed=True,
    )


async def mark_queued_job_failed(job_id: str, error: str) -> None:
    # Truncate error strings to avoid blowing up the column with raw
    # tracebacks — the full detail stays in server logs.
    await _update_queued_job_status(
        job_id, "failed", error=error[:500], mark_processed=True,
    )


async def remove_queued_job(job_id: str, user_id: str) -> bool:
    """Delete a queue entry. Returns True if the row was owned by
    `user_id` and deleted, False otherwise — the API layer turns a
    False into a 404 (not-found / not-yours, same shape as everywhere
    else)."""
    async with await _connect() as db:
        async with db.execute(
            "DELETE FROM queued_jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        ) as cur:
            deleted = cur.rowcount > 0
        await db.commit()
    return deleted


async def get_all_career_entries_for_user(user_id: str) -> list[CareerEntry]:
    async with await _connect() as db:
        async with db.execute(
            "SELECT payload FROM career_entries WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [CareerEntry.model_validate_json(r[0]) for r in rows]


async def rebuild_faiss_index(entries: list[CareerEntry]) -> None:
    """Rebuild the in-memory FAISS index from a list of career entries.

    Useful after bulk imports or when the index file is deleted.
    """
    import numpy as np

    global _faiss_index, _faiss_id_map

    if not entries:
        return

    texts = [e.raw_text for e in entries]
    embeddings = await _embed_batch(texts)
    ids = [e.entry_id for e in entries]

    import faiss as _faiss_lib

    dim = len(embeddings[0])
    index = _faiss_lib.IndexFlatIP(dim)
    arr = np.array(embeddings, dtype="float32")
    _faiss_lib.normalize_L2(arr)
    index.add(arr)

    _faiss_index = index
    _faiss_id_map = ids
    await _faiss_save()


# ---------------------------------------------------------------------------
# Application-assist memory graph
# ---------------------------------------------------------------------------


def _tokens(text: str) -> set[str]:
    """Small lexical tokenizer for the sub-2s assist path.

    This intentionally stays simple and dependency-free: the fast path
    needs deterministic exact-skill matches before any embedding/model
    work. Vector/LLM recall can add nuance, but should not be required
    for the first nudge a user sees while filling a form.
    """

    return {
        t
        for t in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]{2,}", text.lower())
        if t
        not in {
            "and",
            "the",
            "for",
            "with",
            "that",
            "this",
            "your",
            "you",
            "are",
            "was",
            "were",
            "from",
            "about",
            "role",
            "job",
            "team",
        }
    }


def _lexical_score(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    hay = _tokens(text)
    if not hay:
        return 0.0
    overlap = query_tokens & hay
    return min(1.0, len(overlap) / max(3, len(query_tokens)))


async def upsert_application_assist_session(
    session: ApplicationAssistSession,
) -> None:
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO application_assist_sessions
                (assist_session_id, user_id, session_id, job_id, company_name,
                 role_title, payload, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(assist_session_id) DO UPDATE SET
                session_id = excluded.session_id,
                job_id = excluded.job_id,
                company_name = excluded.company_name,
                role_title = excluded.role_title,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (
                session.assist_session_id,
                session.user_id,
                session.session_id,
                session.job_id,
                session.company_name,
                session.role_title,
                session.model_dump_json(),
                session.created_at.isoformat(),
                session.updated_at.isoformat(),
            ),
        )
        await db.commit()


async def get_application_assist_session(
    assist_session_id: str,
) -> Optional[ApplicationAssistSession]:
    async with await _connect() as db:
        async with db.execute(
            "SELECT payload FROM application_assist_sessions WHERE assist_session_id = ?",
            (assist_session_id,),
        ) as cur:
            row = await cur.fetchone()
    return ApplicationAssistSession.model_validate_json(row[0]) if row else None


async def upsert_answer_attempt(attempt: AnswerAttempt) -> None:
    """Persist the full answer attempt, including raw draft/transcript.

    Raw data is retained according to `raw_retention_until`. The table
    keeps the full payload because the Memory Inbox needs source
    provenance and users need to correct extraction errors after the
    background memory job runs.
    """

    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO answer_attempts
                (attempt_id, user_id, assist_session_id, session_id,
                 question_type, visibility, save_status, raw_retention_until,
                 payload, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(attempt_id) DO UPDATE SET
                assist_session_id = excluded.assist_session_id,
                session_id = excluded.session_id,
                question_type = excluded.question_type,
                visibility = excluded.visibility,
                save_status = excluded.save_status,
                raw_retention_until = excluded.raw_retention_until,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (
                attempt.attempt_id,
                attempt.user_id,
                attempt.assist_session_id,
                attempt.session_id,
                attempt.question_type,
                attempt.visibility,
                attempt.save_status,
                attempt.raw_retention_until.isoformat(),
                attempt.model_dump_json(),
                attempt.created_at.isoformat(),
                attempt.updated_at.isoformat(),
            ),
        )
        await db.commit()


async def get_answer_attempt(attempt_id: str) -> Optional[AnswerAttempt]:
    async with await _connect() as db:
        async with db.execute(
            "SELECT payload FROM answer_attempts WHERE attempt_id = ?",
            (attempt_id,),
        ) as cur:
            row = await cur.fetchone()
    return AnswerAttempt.model_validate_json(row[0]) if row else None


async def list_answer_attempts_for_user(
    user_id: str, limit: int = 50,
) -> list[AnswerAttempt]:
    limit = max(1, min(int(limit), 200))
    async with await _connect() as db:
        async with db.execute(
            """
            SELECT payload FROM answer_attempts
            WHERE user_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [AnswerAttempt.model_validate_json(r[0]) for r in rows]


async def purge_expired_answer_attempt_raw(
    *,
    user_id: Optional[str] = None,
    before: Optional[datetime] = None,
) -> int:
    """Remove expired raw drafts/transcripts while retaining final metadata.

    `AnswerAttempt` remains useful for provenance and outcome learning after
    raw text expires. The purge clears only the high-retention-risk fields.
    """

    cutoff = before or _utcnow()
    where = "raw_retention_until <= ?"
    args: list[Any] = [cutoff.isoformat()]
    if user_id:
        where += " AND user_id = ?"
        args.append(user_id)

    async with await _connect() as db:
        async with db.execute(
            f"SELECT attempt_id, payload FROM answer_attempts WHERE {where}",
            tuple(args),
        ) as cur:
            rows = await cur.fetchall()

        purged = 0
        for attempt_id, payload in rows:
            attempt = AnswerAttempt.model_validate_json(payload)
            if not attempt.raw_draft and attempt.transcript is None:
                continue
            attempt.raw_draft = ""
            attempt.transcript = None
            attempt.updated_at = _utcnow()
            await db.execute(
                """
                UPDATE answer_attempts
                SET payload = ?, updated_at = ?
                WHERE attempt_id = ?
                """,
                (attempt.model_dump_json(), attempt.updated_at.isoformat(), attempt_id),
            )
            purged += 1
        await db.commit()
    return purged


async def upsert_experience_atom(atom: ExperienceAtom) -> None:
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO experience_atoms
                (atom_id, user_id, atom_type, text, source_type, source_id,
                 visibility, review_status, sensitive, payload, created_at,
                 updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(atom_id) DO UPDATE SET
                atom_type = excluded.atom_type,
                text = excluded.text,
                source_type = excluded.source_type,
                source_id = excluded.source_id,
                visibility = excluded.visibility,
                review_status = excluded.review_status,
                sensitive = excluded.sensitive,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (
                atom.atom_id,
                atom.user_id,
                atom.atom_type,
                atom.text,
                atom.source_type,
                atom.source_id,
                atom.visibility,
                atom.review_status,
                1 if atom.sensitive else 0,
                atom.model_dump_json(),
                atom.created_at.isoformat(),
                atom.updated_at.isoformat(),
            ),
        )
        await db.commit()


async def upsert_story_frame(story: StoryFrame) -> None:
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO story_frames
                (story_id, user_id, title, summary, visibility, review_status,
                 sensitive, payload, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                visibility = excluded.visibility,
                review_status = excluded.review_status,
                sensitive = excluded.sensitive,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (
                story.story_id,
                story.user_id,
                story.title,
                story.summary,
                story.visibility,
                story.review_status,
                1 if story.sensitive else 0,
                story.model_dump_json(),
                story.created_at.isoformat(),
                story.updated_at.isoformat(),
            ),
        )
        await db.commit()


async def insert_memory_edge(edge: MemoryEdge) -> None:
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO memory_edges
                (edge_id, user_id, source_id, target_id, edge_type, weight,
                 payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(edge_id) DO UPDATE SET
                weight = excluded.weight,
                payload = excluded.payload
            """,
            (
                edge.edge_id,
                edge.user_id,
                edge.source_id,
                edge.target_id,
                edge.edge_type,
                edge.weight,
                edge.model_dump_json(),
                edge.created_at.isoformat(),
            ),
        )
        await db.commit()


async def upsert_advice_snippet(snippet: AdviceSnippet) -> None:
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO advice_snippets
                (advice_id, source_type, topic_tags, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(advice_id) DO UPDATE SET
                source_type = excluded.source_type,
                topic_tags = excluded.topic_tags,
                payload = excluded.payload
            """,
            (
                snippet.advice_id,
                snippet.source_type,
                json.dumps(snippet.topic_tags),
                snippet.model_dump_json(),
                snippet.created_at.isoformat(),
            ),
        )
        await db.commit()


async def list_advice_snippets(
    topic: Optional[str] = None,
    limit: int = 5,
) -> list[AdviceSnippet]:
    limit = max(1, min(int(limit), 20))
    sql = "SELECT payload FROM advice_snippets"
    args: tuple[Any, ...] = ()
    if topic:
        sql += " WHERE topic_tags LIKE ?"
        args = (f"%{topic}%",)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args = (*args, limit)
    async with await _connect() as db:
        async with db.execute(sql, args) as cur:
            rows = await cur.fetchall()
    return [AdviceSnippet.model_validate_json(r[0]) for r in rows]


async def list_memory_inbox(
    user_id: str,
    status: MemoryReviewStatus = "pending",
    limit: int = 100,
) -> dict[str, list[Any]]:
    """Return reviewable memory items with source provenance intact."""

    limit = max(1, min(int(limit), 500))
    async with await _connect() as db:
        async with db.execute(
            """
            SELECT payload FROM experience_atoms
            WHERE user_id = ? AND review_status = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (user_id, status, limit),
        ) as cur:
            atom_rows = await cur.fetchall()
        async with db.execute(
            """
            SELECT payload FROM story_frames
            WHERE user_id = ? AND review_status = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (user_id, status, limit),
        ) as cur:
            story_rows = await cur.fetchall()
    return {
        "experience_atoms": [ExperienceAtom.model_validate_json(r[0]) for r in atom_rows],
        "story_frames": [StoryFrame.model_validate_json(r[0]) for r in story_rows],
    }


async def update_memory_review_status(
    *,
    user_id: str,
    item_kind: str,
    item_id: str,
    review_status: MemoryReviewStatus,
    visibility: Optional[str] = None,
    text: Optional[str] = None,
    title: Optional[str] = None,
    summary: Optional[str] = None,
    angle_tags: Optional[list[str]] = None,
    question_types: Optional[list[str]] = None,
) -> bool:
    """Update Memory Inbox state/content. Returns False for not-found/not-yours."""

    table = {
        "experience_atom": "experience_atoms",
        "story_frame": "story_frames",
    }.get(item_kind)
    id_col = {
        "experience_atom": "atom_id",
        "story_frame": "story_id",
    }.get(item_kind)
    if table is None or id_col is None:
        return False

    async with await _connect() as db:
        async with db.execute(
            f"SELECT payload FROM {table} WHERE {id_col} = ? AND user_id = ?",
            (item_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return False
        model = (
            ExperienceAtom.model_validate_json(row[0])
            if item_kind == "experience_atom"
            else StoryFrame.model_validate_json(row[0])
        )
        model.review_status = review_status
        if visibility in {"normal", "private"}:
            model.visibility = visibility  # type: ignore[assignment]
        if isinstance(model, ExperienceAtom):
            if text is not None:
                model.text = text
        else:
            if title is not None:
                model.title = title
            if summary is not None:
                model.summary = summary
            if angle_tags is not None:
                model.angle_tags = angle_tags
            if question_types is not None:
                model.question_types = question_types  # type: ignore[assignment]
        model.updated_at = _utcnow()
        await db.execute(
            f"""
            UPDATE {table}
            SET review_status = ?, visibility = ?, payload = ?, updated_at = ?
            WHERE {id_col} = ? AND user_id = ?
            """,
            (
                model.review_status,
                model.visibility,
                model.model_dump_json(),
                model.updated_at.isoformat(),
                item_id,
                user_id,
            ),
        )
        await db.commit()
    return True


async def hard_delete_memory_item(
    *,
    user_id: str,
    item_kind: str,
    item_id: str,
) -> bool:
    """Physically delete a memory item and its direct graph edges."""

    table = {
        "experience_atom": "experience_atoms",
        "story_frame": "story_frames",
    }.get(item_kind)
    id_col = {
        "experience_atom": "atom_id",
        "story_frame": "story_id",
    }.get(item_kind)
    if table is None or id_col is None:
        return False

    async with await _connect() as db:
        async with db.execute(
            f"SELECT 1 FROM {table} WHERE {id_col} = ? AND user_id = ?",
            (item_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return False
        await db.execute(
            """
            DELETE FROM memory_edges
            WHERE user_id = ? AND (source_id = ? OR target_id = ?)
            """,
            (user_id, item_id, item_id),
        )
        await db.execute(
            f"DELETE FROM {table} WHERE {id_col} = ? AND user_id = ?",
            (item_id, user_id),
        )
        await db.commit()
    return True


async def export_user_memory(
    *,
    user_id: str,
    include_raw: bool = True,
) -> dict[str, list[Any]]:
    """Export the user's assist memory graph and answer-attempt provenance."""

    async with await _connect() as db:
        async with db.execute(
            "SELECT payload FROM answer_attempts WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ) as cur:
            attempt_rows = await cur.fetchall()
        async with db.execute(
            "SELECT payload FROM experience_atoms WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ) as cur:
            atom_rows = await cur.fetchall()
        async with db.execute(
            "SELECT payload FROM story_frames WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ) as cur:
            story_rows = await cur.fetchall()

    attempts = [AnswerAttempt.model_validate_json(r[0]) for r in attempt_rows]
    if not include_raw:
        for attempt in attempts:
            attempt.raw_draft = ""
            attempt.transcript = None

    return {
        "answer_attempts": attempts,
        "experience_atoms": [ExperienceAtom.model_validate_json(r[0]) for r in atom_rows],
        "story_frames": [StoryFrame.model_validate_json(r[0]) for r in story_rows],
    }


async def merge_memory_items(
    *,
    user_id: str,
    item_kind: str,
    target_item_id: str,
    source_item_ids: list[str],
    merged_text: Optional[str] = None,
    title: Optional[str] = None,
    visibility: Optional[str] = None,
) -> int:
    """Merge same-kind inbox items into a target and tombstone the sources."""

    table = {
        "experience_atom": "experience_atoms",
        "story_frame": "story_frames",
    }.get(item_kind)
    id_col = {
        "experience_atom": "atom_id",
        "story_frame": "story_id",
    }.get(item_kind)
    if table is None or id_col is None:
        return 0

    source_ids = [item_id for item_id in source_item_ids if item_id != target_item_id]
    if not source_ids:
        return 0

    async with await _connect() as db:
        async with db.execute(
            f"SELECT payload FROM {table} WHERE {id_col} = ? AND user_id = ?",
            (target_item_id, user_id),
        ) as cur:
            target_row = await cur.fetchone()
        if not target_row:
            return 0

        source_rows: list[tuple[str, str]] = []
        for source_id in source_ids:
            async with db.execute(
                f"SELECT {id_col}, payload FROM {table} WHERE {id_col} = ? AND user_id = ?",
                (source_id, user_id),
            ) as cur:
                row = await cur.fetchone()
            if row:
                source_rows.append(row)
        if not source_rows:
            return 0

        if item_kind == "experience_atom":
            target = ExperienceAtom.model_validate_json(target_row[0])
            sources = [ExperienceAtom.model_validate_json(row[1]) for row in source_rows]
            target.text = merged_text or "\n".join(
                dict.fromkeys([target.text, *(source.text for source in sources)])
            )
            target.confidence = max([target.confidence, *(source.confidence for source in sources)])
            target.sensitive = target.sensitive or any(source.sensitive for source in sources)
            if visibility in {"normal", "private"}:
                target.visibility = visibility  # type: ignore[assignment]
            elif target.sensitive or any(source.visibility == "private" for source in sources):
                target.visibility = "private"
        else:
            target = StoryFrame.model_validate_json(target_row[0])
            sources = [StoryFrame.model_validate_json(row[1]) for row in source_rows]
            if title is not None:
                target.title = title
            target.summary = merged_text or "\n\n".join(
                dict.fromkeys([target.summary, *(source.summary for source in sources)])
            )
            target.angle_tags = list(dict.fromkeys([
                *target.angle_tags,
                *(tag for source in sources for tag in source.angle_tags),
            ]))
            target.question_types = list(dict.fromkeys([
                *target.question_types,
                *(q for source in sources for q in source.question_types),
            ]))
            target.atom_ids = list(dict.fromkeys([
                *target.atom_ids,
                *(atom_id for source in sources for atom_id in source.atom_ids),
            ]))
            target.sensitive = target.sensitive or any(source.sensitive for source in sources)
            if visibility in {"normal", "private"}:
                target.visibility = visibility  # type: ignore[assignment]
            elif target.sensitive or any(source.visibility == "private" for source in sources):
                target.visibility = "private"

        target.review_status = "pending"
        target.updated_at = _utcnow()
        await db.execute(
            f"""
            UPDATE {table}
            SET payload = ?, visibility = ?, review_status = ?, updated_at = ?
            WHERE {id_col} = ? AND user_id = ?
            """,
            (
                target.model_dump_json(),
                target.visibility,
                target.review_status,
                target.updated_at.isoformat(),
                target_item_id,
                user_id,
            ),
        )

        for source_id, payload in source_rows:
            source = (
                ExperienceAtom.model_validate_json(payload)
                if item_kind == "experience_atom"
                else StoryFrame.model_validate_json(payload)
            )
            source.review_status = "deleted"
            source.updated_at = _utcnow()
            await db.execute(
                f"""
                UPDATE {table}
                SET payload = ?, review_status = ?, updated_at = ?
                WHERE {id_col} = ? AND user_id = ?
                """,
                (
                    source.model_dump_json(),
                    source.review_status,
                    source.updated_at.isoformat(),
                    source_id,
                    user_id,
                ),
            )
        await db.commit()
    return len(source_rows)


async def retrieve_application_memory_suggestions(
    *,
    user_id: str,
    query_text: str,
    question_type: Optional[QuestionType] = None,
    k: int = 5,
    include_private: bool = False,
) -> list[MemorySuggestion]:
    """Hybrid memory recall for the live assist path.

    The implementation deliberately prioritises deterministic lexical
    matching over slower model calls. It also gates private and pending
    memories by default: only approved, normal-visibility atoms/stories
    can influence future suggestions unless the caller explicitly opts
    into private recall.
    """

    query_tokens = _tokens(query_text)
    suggestions: list[MemorySuggestion] = []

    # Existing career entries are semantically searchable through the
    # current FAISS index. Treat them as already user-owned memories.
    try:
        career_entries = await retrieve_relevant_entries(
            user_id=user_id,
            query_text=query_text,
            k=max(k, 8),
            kind_weights=STAR_BOOST_KINDS,
        )
    except Exception as exc:
        logger.info("career-entry semantic recall skipped: %s", exc)
        career_entries = []
    for entry in career_entries:
        lexical = _lexical_score(query_tokens, entry.raw_text)
        score = 0.55 + lexical
        if entry.kind in STAR_BOOST_KINDS:
            score += 0.15
        suggestions.append(
            MemorySuggestion(
                memory_id=entry.entry_id,
                memory_kind="career_entry",
                title=entry.kind.replace("_", " ").title(),
                text=entry.raw_text[:600],
                score=round(score, 3),
                rationale="Relevant career-store entry from semantic recall.",
                warnings=[],
            )
        )

    visibility_clause = "" if include_private else " AND visibility = 'normal'"
    async with await _connect() as db:
        async with db.execute(
            f"""
            SELECT payload FROM experience_atoms
            WHERE user_id = ?
              AND review_status = 'approved'
              {visibility_clause}
            ORDER BY updated_at DESC
            LIMIT 200
            """,
            (user_id,),
        ) as cur:
            atom_rows = await cur.fetchall()
        async with db.execute(
            f"""
            SELECT payload FROM story_frames
            WHERE user_id = ?
              AND review_status = 'approved'
              {visibility_clause}
            ORDER BY updated_at DESC
            LIMIT 200
            """,
            (user_id,),
        ) as cur:
            story_rows = await cur.fetchall()

    for row in atom_rows:
        atom = ExperienceAtom.model_validate_json(row[0])
        lexical = _lexical_score(query_tokens, atom.text)
        if lexical <= 0:
            continue
        warnings = ["Private memory"] if atom.visibility == "private" else []
        suggestions.append(
            MemorySuggestion(
                memory_id=atom.atom_id,
                memory_kind="experience_atom",
                title=atom.atom_type.replace("_", " ").title(),
                text=atom.text,
                score=round(lexical + atom.confidence * 0.2, 3),
                rationale="Exact terms in this memory match the question/JD.",
                warnings=warnings,
            )
        )

    for row in story_rows:
        story = StoryFrame.model_validate_json(row[0])
        lexical = _lexical_score(query_tokens, f"{story.title} {story.summary} {' '.join(story.angle_tags)}")
        if question_type and question_type in story.question_types:
            lexical += 0.25
        lexical += max(-0.3, min(0.3, story.outcome_score * 0.25))
        warnings = []
        if story.usage_count >= 3:
            lexical -= 0.15
            warnings.append("Used several times already")
        if story.visibility == "private":
            warnings.append("Private memory")
        if lexical <= 0:
            continue
        suggestions.append(
            MemorySuggestion(
                memory_id=story.story_id,
                memory_kind="story_frame",
                title=story.title,
                text=story.summary,
                score=round(lexical, 3),
                rationale="Story angle matches the question type or exact role terms.",
                warnings=warnings,
                outcome_signal=(
                    "positive" if story.outcome_score > 0.2 else
                    "weak" if story.outcome_score < -0.2 else None
                ),
            )
        )

    # Keep one item per memory id, highest score wins.
    best: dict[str, MemorySuggestion] = {}
    for suggestion in suggestions:
        old = best.get(suggestion.memory_id)
        if old is None or suggestion.score > old.score:
            best[suggestion.memory_id] = suggestion
    ranked = sorted(best.values(), key=lambda s: s.score, reverse=True)
    return ranked[: max(1, min(int(k), 20))]


# ---------------------------------------------------------------------------
# Storage class — thin wrapper for dependency injection
# ---------------------------------------------------------------------------


class Storage:
    """Thin class wrapper around module-level storage functions.

    Passed through orchestrator so it can be tested without touching
    a real DB. For the single-user demo, one instance is created at
    startup and stored on app.state.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        # Tests can pass a custom DB path; mutate the shared settings only when
        # the override is concrete (no `:memory:` — aiosqlite would still need
        # a file path) and only when no other Storage instance has already
        # initialised the schema, so a unit test does not accidentally
        # repoint a live process.
        if db_path and db_path != ":memory:":
            global _initialised
            if _initialised:
                # Refuse to silently switch the DB out from under live state.
                raise RuntimeError(
                    "Storage already initialised against "
                    f"{settings.sqlite_db_path}; cannot rebind to {db_path}."
                )
            settings.sqlite_db_path = Path(db_path)

    async def initialise(self) -> None:
        if settings.storage_backend == "supabase_postgres":
            raise RuntimeError(
                "STORAGE_BACKEND=supabase_postgres is a hosted V2 release "
                "gate, but the async Supabase Postgres storage adapter is "
                "not implemented yet. Apply supabase/migrations first and "
                "keep hosted deploys blocked until the adapter replaces the "
                "SQLite/FAISS path."
            )
        await _ensure_db()

    async def close(self) -> None:
        pass  # connections are per-request; nothing to close

    # ── User profiles ──────────────────────────────────────────────────────

    async def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        return await get_user_profile(user_id)

    async def save_user_profile(self, profile: UserProfile) -> None:
        await upsert_user_profile(profile)

    # ── Career entries ─────────────────────────────────────────────────────

    async def insert_career_entry(self, entry: CareerEntry) -> None:
        await insert_career_entry(entry)

    async def insert_career_entries_batch(
        self, entries: list[CareerEntry],
    ) -> None:
        await insert_career_entries_batch(entries)

    async def retrieve_relevant_entries(
        self,
        user_id: str,
        query: str,
        k: int = 8,
        kind_weights: Optional[dict[str, float]] = None,
    ) -> list[CareerEntry]:
        # Module-level fn is `(user_id, query_text, k, kind_weights)`; the
        # wrapper accepts `query` for caller ergonomics and forwards under
        # the right kwarg.
        return await retrieve_relevant_entries(
            user_id=user_id, query_text=query, k=k, kind_weights=kind_weights,
        )

    async def get_all_career_entries(self) -> list[CareerEntry]:
        async with await _connect() as db:
            async with db.execute(
                "SELECT payload FROM career_entries ORDER BY created_at"
            ) as cur:
                rows = await cur.fetchall()
        return [CareerEntry.model_validate_json(r[0]) for r in rows]

    async def rebuild_index(self, entries: list[CareerEntry]) -> None:
        await rebuild_faiss_index(entries)

    # ── Application-assist memory graph ───────────────────────────────────

    async def save_application_assist_session(
        self, session: ApplicationAssistSession,
    ) -> None:
        await upsert_application_assist_session(session)

    async def get_application_assist_session(
        self, assist_session_id: str,
    ) -> Optional[ApplicationAssistSession]:
        return await get_application_assist_session(assist_session_id)

    async def save_answer_attempt(self, attempt: AnswerAttempt) -> None:
        await upsert_answer_attempt(attempt)

    async def get_answer_attempt(self, attempt_id: str) -> Optional[AnswerAttempt]:
        return await get_answer_attempt(attempt_id)

    async def list_answer_attempts_for_user(
        self, user_id: str, limit: int = 50,
    ) -> list[AnswerAttempt]:
        return await list_answer_attempts_for_user(user_id, limit=limit)

    async def purge_expired_answer_attempt_raw(
        self,
        *,
        user_id: Optional[str] = None,
        before: Optional[datetime] = None,
    ) -> int:
        return await purge_expired_answer_attempt_raw(user_id=user_id, before=before)

    async def save_experience_atom(self, atom: ExperienceAtom) -> None:
        await upsert_experience_atom(atom)

    async def save_story_frame(self, story: StoryFrame) -> None:
        await upsert_story_frame(story)

    async def save_memory_edge(self, edge: MemoryEdge) -> None:
        await insert_memory_edge(edge)

    async def save_advice_snippet(self, snippet: AdviceSnippet) -> None:
        await upsert_advice_snippet(snippet)

    async def list_advice_snippets(
        self, topic: Optional[str] = None, limit: int = 5,
    ) -> list[AdviceSnippet]:
        return await list_advice_snippets(topic=topic, limit=limit)

    async def list_memory_inbox(
        self,
        user_id: str,
        status: MemoryReviewStatus = "pending",
        limit: int = 100,
    ) -> dict[str, list[Any]]:
        return await list_memory_inbox(user_id=user_id, status=status, limit=limit)

    async def update_memory_review_status(
        self,
        *,
        user_id: str,
        item_kind: str,
        item_id: str,
        review_status: MemoryReviewStatus,
        visibility: Optional[str] = None,
        text: Optional[str] = None,
        title: Optional[str] = None,
        summary: Optional[str] = None,
        angle_tags: Optional[list[str]] = None,
        question_types: Optional[list[str]] = None,
    ) -> bool:
        return await update_memory_review_status(
            user_id=user_id,
            item_kind=item_kind,
            item_id=item_id,
            review_status=review_status,
            visibility=visibility,
            text=text,
            title=title,
            summary=summary,
            angle_tags=angle_tags,
            question_types=question_types,
        )

    async def hard_delete_memory_item(
        self,
        *,
        user_id: str,
        item_kind: str,
        item_id: str,
    ) -> bool:
        return await hard_delete_memory_item(
            user_id=user_id,
            item_kind=item_kind,
            item_id=item_id,
        )

    async def export_user_memory(
        self,
        *,
        user_id: str,
        include_raw: bool = True,
    ) -> dict[str, list[Any]]:
        return await export_user_memory(user_id=user_id, include_raw=include_raw)

    async def merge_memory_items(
        self,
        *,
        user_id: str,
        item_kind: str,
        target_item_id: str,
        source_item_ids: list[str],
        merged_text: Optional[str] = None,
        title: Optional[str] = None,
        visibility: Optional[str] = None,
    ) -> int:
        return await merge_memory_items(
            user_id=user_id,
            item_kind=item_kind,
            target_item_id=target_item_id,
            source_item_ids=source_item_ids,
            merged_text=merged_text,
            title=title,
            visibility=visibility,
        )

    async def retrieve_application_memory_suggestions(
        self,
        *,
        user_id: str,
        query_text: str,
        question_type: Optional[QuestionType] = None,
        k: int = 5,
        include_private: bool = False,
    ) -> list[MemorySuggestion]:
        return await retrieve_application_memory_suggestions(
            user_id=user_id,
            query_text=query_text,
            question_type=question_type,
            k=k,
            include_private=include_private,
        )

    # ── Writing style profiles ─────────────────────────────────────────────

    async def get_writing_style_profile(
        self, profile_id_or_user_id: str
    ) -> Optional[WritingStyleProfile]:
        return await get_writing_style_profile(profile_id_or_user_id)

    async def save_writing_style_profile(self, profile: WritingStyleProfile) -> None:
        await upsert_writing_style_profile(profile)

    # ── Sessions ───────────────────────────────────────────────────────────

    async def save_session(self, session: Session) -> None:
        await insert_session(session)

    async def get_session(self, session_id: str) -> Optional[Session]:
        return await get_session(session_id)

    async def get_recent_sessions(self, user_id: str, limit: int = 5) -> list[Session]:
        return await get_recent_sessions(user_id=user_id, n=limit)

    async def append_session_progress_event(
        self, session_id: str, event: dict[str, Any]
    ) -> None:
        await append_session_progress_event(session_id=session_id, event=event)

    async def get_session_progress_events(
        self, session_id: str,
    ) -> list[dict[str, Any]]:
        return await get_session_progress_events(session_id=session_id)

    async def session_cost_summary(self, session_id: str) -> dict:
        return await session_cost_summary(session_id=session_id)

    async def record_quota_usage(
        self,
        *,
        user_id: str,
        category: str,
        units: int = 1,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return await record_quota_usage(
            user_id=user_id,
            category=category,
            units=units,
            metadata=metadata,
        )

    async def append_security_audit_event(
        self,
        *,
        event_type: str,
        user_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        await append_security_audit_event(
            event_type=event_type,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
        )

    async def create_extension_pairing_token(
        self,
        *,
        user_id: str,
        ttl_minutes: int = 10,
    ) -> dict[str, Any]:
        return await create_extension_pairing_token(
            user_id=user_id,
            ttl_minutes=ttl_minutes,
        )

    async def consume_extension_pairing_token(
        self,
        token: str,
    ) -> Optional[dict[str, Any]]:
        return await consume_extension_pairing_token(token)

    # ── Queued jobs ────────────────────────────────────────────────────────

    async def insert_queued_job(self, user_id: str, job_url: str) -> QueuedJob:
        return await insert_queued_job(user_id=user_id, job_url=job_url)

    async def list_queued_jobs(
        self, user_id: str, status_filter: Optional[str] = None,
    ) -> list[QueuedJob]:
        return await list_queued_jobs(
            user_id=user_id, status_filter=status_filter,
        )

    async def get_queued_job(self, job_id: str) -> Optional[QueuedJob]:
        return await get_queued_job(job_id=job_id)

    async def mark_queued_job_processing(self, job_id: str) -> None:
        await mark_queued_job_processing(job_id=job_id)

    async def mark_queued_job_done(
        self, job_id: str, session_id: str,
    ) -> None:
        await mark_queued_job_done(job_id=job_id, session_id=session_id)

    async def mark_queued_job_failed(self, job_id: str, error: str) -> None:
        await mark_queued_job_failed(job_id=job_id, error=error)

    async def remove_queued_job(self, job_id: str, user_id: str) -> bool:
        return await remove_queued_job(job_id=job_id, user_id=user_id)

    async def save_phase1_output(self, session_id: str, bundle) -> None:
        session = await get_session(session_id)
        if session:
            session.phase1_output = bundle.model_dump(mode="json")
            await update_session(session)

    async def save_verdict(self, session_id: str, verdict) -> None:
        session = await get_session(session_id)
        if session:
            # Single source of truth: Session.verdict is always a Verdict
            # instance, never a dict. Coerce here so callers can pass
            # either without scattering isinstance() checks everywhere.
            from .schemas import Verdict

            if isinstance(verdict, dict):
                verdict = Verdict.model_validate(verdict)
            session.verdict = verdict
            await update_session(session)

    # ── Scraped pages ──────────────────────────────────────────────────────

    async def cache_scraped_page(self, url: str, text: str, fetched_at: datetime) -> None:
        await cache_scraped_page(url=url, text=text, fetched_at=fetched_at)

    async def get_cached_page(self, url: str, max_age_hours: int = 24) -> Optional[str]:
        return await get_cached_page(url=url, max_age_hours=max_age_hours)


# ===========================================================================
# Managed-session cache + Job entity (PROCESS Entry 45)
# --- Job entity --------------------------------------------------------------



async def upsert_job(
    *,
    user_id: str,
    role_title: str,
    company_name: str,
    company_domain: Optional[str] = None,
    last_seen_url: Optional[str] = None,
) -> str:
    """Find-or-create a Job by (user_id, role_title, company_name).

    Returns the job_id. Updates last_seen_url + last_seen_at on hit.
    Identity is intentionally lax — same role at same company = same job
    even if the URL changes (re-listing, expired-and-replaced).
    """
    import uuid
    role_norm = (role_title or "").strip()
    company_norm = (company_name or "").strip()
    now = _utcnow().isoformat()
    async with await _connect() as db:
        async with db.execute(
            "SELECT job_id FROM jobs WHERE user_id = ? AND role_title = ? "
            "AND company_name = ? LIMIT 1",
            (user_id, role_norm, company_norm),
        ) as cur:
            row = await cur.fetchone()
        if row:
            job_id = row[0]
            await db.execute(
                "UPDATE jobs SET last_seen_url = COALESCE(?, last_seen_url), "
                "last_seen_at = ?, company_domain = COALESCE(?, company_domain) "
                "WHERE job_id = ?",
                (last_seen_url, now, company_domain, job_id),
            )
        else:
            job_id = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO jobs (job_id, user_id, role_title, company_name, "
                "company_domain, last_seen_url, last_seen_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, user_id, role_norm, company_norm,
                 company_domain, last_seen_url, now, now),
            )
        await db.commit()
    return job_id


async def find_jobs_for_user(
    user_id: str,
    *,
    company_substring: Optional[str] = None,
    role_substring: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """Find recent jobs for a user, optionally filtered by company / role
    substring (case-insensitive). Used to disambiguate
    'draft me a CV for that Acme role' → which Acme role exactly?
    """
    sql = (
        "SELECT job_id, role_title, company_name, company_domain, "
        "last_seen_url, last_seen_at, created_at FROM jobs WHERE user_id = ?"
    )
    args: list = [user_id]
    if company_substring:
        sql += " AND LOWER(company_name) LIKE ?"
        args.append(f"%{company_substring.lower()}%")
    if role_substring:
        sql += " AND LOWER(role_title) LIKE ?"
        args.append(f"%{role_substring.lower()}%")
    sql += " ORDER BY last_seen_at DESC LIMIT ?"
    args.append(limit)
    async with await _connect() as db:
        async with db.execute(sql, args) as cur:
            rows = await cur.fetchall()
    return [
        {
            "job_id": r[0], "role_title": r[1], "company_name": r[2],
            "company_domain": r[3], "last_seen_url": r[4],
            "last_seen_at": r[5], "created_at": r[6],
        }
        for r in rows
    ]


async def get_session_for_job(
    user_id: str, job_id: str,
) -> Optional[Session]:
    """Return the most-recent session for a job_id."""
    async with await _connect() as db:
        async with db.execute(
            "SELECT s.payload FROM sessions s WHERE s.user_id = ? "
            "AND json_extract(s.payload, '$.job_id') = ? "
            "ORDER BY s.created_at DESC LIMIT 1",
            (user_id, job_id),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    try:
        return Session.model_validate_json(row[0])
    except Exception:
        return None
