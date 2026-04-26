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
import json
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
    CareerEntry,
    QueuedJob,
    Session,
    UserProfile,
    WritingStyleProfile,
)

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
    WAL) so concurrent writers from the bot + FastAPI + test harness
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


async def _connect():
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

    async def _connect_with_pragmas():
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

    async def _open(self):
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


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        with _embedding_lock:
            if _embedding_model is None:
                from sentence_transformers import SentenceTransformer

                _embedding_model = SentenceTransformer(settings.embedding_model_name)
    return _embedding_model


_faiss_index = None
_faiss_id_map: list[str] = []  # position-in-index -> entry_id
_faiss_lock = threading.Lock()


def _faiss():
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
    hits: list[tuple[int, float, str]] = []
    for pos, (i, score) in enumerate(zip(idxs[0], scores[0])):
        if 0 <= i < len(id_map):
            hits.append((pos, float(score), id_map[i]))
    if not hits:
        return []

    hit_ids = [eid for (_, _, eid) in hits]
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

    by_id: dict[str, CareerEntry] = {}
    for r in rows:
        entry = CareerEntry.model_validate_json(r[0])
        by_id[entry.entry_id] = entry

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


# Approximate $/token prices (verify before production).
# Opus 4.7 and Sonnet 4.6 pricing intentionally conservative here.
# Public Anthropic list prices in USD per 1M tokens. Cross-checked
# against https://www.anthropic.com/pricing on 2026-04-25 for:
#   - claude-opus-4-7
#   - claude-sonnet-4-6
#   - claude-haiku-4-5
# These feed `estimate_cost_usd` to populate `llm_cost_log.cost_usd`
# at every `log_llm_cost(...)` call. Update this table when Anthropic
# revises list prices, or when a new model bucket lands. The runtime
# already records the upstream `usage` block (real Anthropic-side
# token counts) — only the per-token-class USD rate is local.
#
# Anthropic also exposes a retrospective billing API at
# `/v1/organizations/usage_report/messages` for true post-hoc
# reconciliation; this codebase doesn't pull from it (the local
# computation is good enough for credit-budget refusal and the
# smoke rollup, both of which run pre-billing-cycle). If the
# numbers in `llm_cost_log` ever diverge meaningfully from the
# admin API, that's the cue to wire a reconciliation job rather
# than nudge these constants.
_PRICING_LAST_VERIFIED = "2026-04-26"
_PRICING_USD_PER_MTOK = {
    # Anthropic
    "opus":   {"input": 15.0, "output": 75.0},
    "sonnet": {"input":  3.0, "output": 15.0},
    "haiku":  {"input":  0.80, "output":  4.0},
    # OpenAI (PROCESS Entry 44 — multi-provider CV tailor)
    # gpt-4o-2024-08-06: $2.50 / $10 per Mtok.
    "gpt-4o": {"input":  2.50, "output": 10.0},
    "gpt-5":  {"input":  5.0, "output": 20.0},   # placeholder — verify on launch
    # Cohere (Command R+ Aug 2024): $2.50 / $10 per Mtok.
    "command-r-plus": {"input": 2.50, "output": 10.0},
    "command-r":      {"input": 0.50, "output":  1.50},
}


def _price_bucket(model: str) -> dict[str, float]:
    m = model.lower()
    # Anthropic family
    if "opus" in m:
        return _PRICING_USD_PER_MTOK["opus"]
    if "sonnet" in m:
        return _PRICING_USD_PER_MTOK["sonnet"]
    if "haiku" in m:
        return _PRICING_USD_PER_MTOK["haiku"]
    # OpenAI family
    if "gpt-4o" in m or "gpt4o" in m:
        return _PRICING_USD_PER_MTOK["gpt-4o"]
    if "gpt-5" in m or "gpt5" in m:
        return _PRICING_USD_PER_MTOK["gpt-5"]
    # Cohere family
    if "command-r-plus" in m or "command-r+" in m:
        return _PRICING_USD_PER_MTOK["command-r-plus"]
    if "command-r" in m or "command" in m:
        return _PRICING_USD_PER_MTOK["command-r"]
    # Unknown — use Sonnet pricing as a conservative default. Better to
    # overestimate than have an unknown-priced call sneak under the
    # credit-budget refusal.
    return _PRICING_USD_PER_MTOK["sonnet"]


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    """Anthropic prompt-caching pricing (B1/B2):

    - cache_creation_tokens: ~1.25x the base input rate (write).
    - cache_read_tokens: ~0.1x the base input rate (read hit).
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


async def get_all_career_entries() -> list[CareerEntry]:
    async with await _connect() as db:
        async with db.execute(
            "SELECT payload FROM career_entries ORDER BY created_at"
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

    embeddings = []
    ids: list[str] = []
    for entry in entries:
        emb = await _embed(entry.raw_text)
        embeddings.append(emb)
        ids.append(entry.entry_id)

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
# Storage class — thin wrapper for dependency injection
# ---------------------------------------------------------------------------


class Storage:
    """Thin class wrapper around module-level storage functions.

    Passed through orchestrator and bot handlers so they can be tested
    without touching a real DB. For the single-user demo, one instance
    is created at bot startup and stored in bot_data["storage"].
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
        return await get_all_career_entries()

    async def rebuild_index(self, entries: list[CareerEntry]) -> None:
        await rebuild_faiss_index(entries)

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

    async def session_cost_summary(self, session_id: str) -> dict:
        return await session_cost_summary(session_id=session_id)

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
