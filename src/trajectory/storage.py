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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from .config import settings
from .schemas import (
    CareerEntry,
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
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cost_agent ON llm_cost_log(agent_name);
"""


# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------


_init_lock = asyncio.Lock()
_initialised = False


async def _ensure_db() -> None:
    """Create the DB file and tables if they don't exist. Idempotent."""
    global _initialised
    if _initialised:
        return
    async with _init_lock:
        if _initialised:
            return
        settings.sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(settings.sqlite_db_path) as db:
            await db.executescript(_SCHEMA_SQL)
            await db.commit()
        _initialised = True


async def _connect() -> aiosqlite.Connection:
    await _ensure_db()
    return await aiosqlite.connect(settings.sqlite_db_path)


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
            (profile.user_id, profile.model_dump_json(), datetime.utcnow().isoformat()),
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


def _faiss_save() -> None:
    import faiss

    path = settings.faiss_index_path
    path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(_faiss_index, str(path))
    Path(str(path) + ".ids.json").write_text(json.dumps(_faiss_id_map))


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
        _faiss_save()


async def retrieve_relevant_entries(
    user_id: str,
    query_text: str,
    k: int = 12,
) -> list[CareerEntry]:
    """FAISS nearest-neighbour over career entries for this user.

    We over-fetch from FAISS and filter by user in Python — acceptable for
    single-user demo scale. For multi-user at scale, partition by user_id.
    """
    import numpy as np

    index, id_map = _faiss()
    if index.ntotal == 0 or not id_map:
        return []

    query_vec = np.asarray([await _embed(query_text)], dtype="float32")
    over_fetch = min(index.ntotal, max(k * 4, 32))
    _, idxs = index.search(query_vec, over_fetch)

    hit_ids: list[str] = []
    for i in idxs[0]:
        if 0 <= i < len(id_map):
            hit_ids.append(id_map[i])
    if not hit_ids:
        return []

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

    # Re-rank in FAISS-hit order.
    by_id = {CareerEntry.model_validate_json(r[0]).entry_id: r[0] for r in rows}
    ordered: list[CareerEntry] = []
    for eid in hit_ids:
        if eid in by_id:
            ordered.append(CareerEntry.model_validate_json(by_id[eid]))
            if len(ordered) >= k:
                break
    return ordered


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
                datetime.utcnow().isoformat(),
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
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
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
_PRICING_USD_PER_MTOK = {
    "opus": {"input": 15.0, "output": 75.0},
    "sonnet": {"input": 3.0, "output": 15.0},
    "haiku": {"input": 0.80, "output": 4.0},
}


def _price_bucket(model: str) -> dict[str, float]:
    m = model.lower()
    if "opus" in m:
        return _PRICING_USD_PER_MTOK["opus"]
    if "sonnet" in m:
        return _PRICING_USD_PER_MTOK["sonnet"]
    if "haiku" in m:
        return _PRICING_USD_PER_MTOK["haiku"]
    return _PRICING_USD_PER_MTOK["sonnet"]


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    p = _price_bucket(model)
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


async def log_llm_cost(
    session_id: Optional[str],
    agent_name: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    cost = estimate_cost_usd(model, input_tokens, output_tokens)
    async with await _connect() as db:
        await db.execute(
            """
            INSERT INTO llm_cost_log
                (session_id, agent_name, model,
                 input_tokens, output_tokens, cost_usd, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                agent_name,
                model,
                input_tokens,
                output_tokens,
                cost,
                datetime.utcnow().isoformat(),
            ),
        )
        await db.commit()


async def total_cost_usd() -> float:
    async with await _connect() as db:
        async with db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_cost_log") as cur:
            row = await cur.fetchone()
    return float(row[0]) if row else 0.0
