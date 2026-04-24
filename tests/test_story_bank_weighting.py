"""Tests for STAR_BOOST_KINDS retrieval weighting (#2 — story bank).

End-to-end against a real FAISS + SQLite (per-test tempdir) so the
actual ranking order matters, not a mock. We seed two near-identical
entries about the same topic — one as a `cv_bullet`, one as a
`star_polish` — and verify the polished story wins when kind_weights
is active.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trajectory.schemas import CareerEntry


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def isolated_storage(tmp_path: Path, monkeypatch):
    """Fresh SQLite + FAISS per test; reset the init flag + FAISS
    singletons so the index starts empty."""
    from trajectory.config import settings
    from trajectory import storage as storage_module

    monkeypatch.setattr(settings, "sqlite_db_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "faiss_index_path", tmp_path / "test.faiss")
    monkeypatch.setattr(storage_module, "_initialised", False)
    monkeypatch.setattr(storage_module, "_faiss_index", None)
    monkeypatch.setattr(storage_module, "_faiss_id_map", [])
    yield


def _seed(coro):
    return asyncio.run(coro)


def _entry(entry_id: str, kind: str, text: str) -> CareerEntry:
    return CareerEntry(
        entry_id=entry_id,
        user_id="u1",
        kind=kind,  # type: ignore[arg-type]
        raw_text=text,
        created_at=_now(),
    )


# ---------------------------------------------------------------------------
# Baseline: behaviour without weights is unchanged
# ---------------------------------------------------------------------------


def test_retrieval_without_weights_preserves_faiss_order(isolated_storage):
    from trajectory.storage import insert_career_entry, retrieve_relevant_entries

    _seed(insert_career_entry(_entry(
        "e1", "cv_bullet",
        "Shipped the observability rewrite reducing p99 latency 40%.",
    )))
    _seed(insert_career_entry(_entry(
        "e2", "project_note",
        "Ran an A/B test for ranking — lifted CTR 12%.",
    )))
    _seed(insert_career_entry(_entry(
        "e3", "star_polish",
        "Designed a new team culture manifesto — completely unrelated.",
    )))

    hits = _seed(retrieve_relevant_entries(
        user_id="u1", query_text="observability latency rewrite", k=3,
    ))
    ids = [h.entry_id for h in hits]
    assert ids[0] == "e1", f"pure FAISS should rank most-similar first, got {ids}"


# ---------------------------------------------------------------------------
# STAR boost flips a borderline tie
# ---------------------------------------------------------------------------


def test_star_boost_flips_borderline_ranking(isolated_storage):
    """When a star_polish entry is ~equally semantically similar to
    the query, the boost should push it ahead of the cv_bullet."""
    from trajectory.storage import insert_career_entry, retrieve_relevant_entries

    _seed(insert_career_entry(_entry(
        "bullet", "cv_bullet",
        "Led migration from monolith to microservices at scale.",
    )))
    _seed(insert_career_entry(_entry(
        "polish", "star_polish",
        "Led migration from monolith to microservices — Situation: "
        "legacy PHP app with 90s p99. Task: new architecture. "
        "Action: strangler fig with service boundaries by domain. "
        "Result: p99 down to 12s within six months.",
    )))

    # Without boost — FAISS similarity alone; bullet might win or tie.
    base = _seed(retrieve_relevant_entries(
        user_id="u1", query_text="migration monolith microservices", k=2,
    ))
    base_ids = [h.entry_id for h in base]

    # With boost — polish should win decisively.
    boosted = _seed(retrieve_relevant_entries(
        user_id="u1",
        query_text="migration monolith microservices",
        k=2,
        kind_weights={"star_polish": 1.5, "qa_answer": 1.2},
    ))
    boosted_ids = [h.entry_id for h in boosted]

    assert boosted_ids[0] == "polish", (
        f"STAR boost should rank polish first; got {boosted_ids} (baseline: {base_ids})"
    )


def test_boost_respects_kind_not_in_weights(isolated_storage):
    """Kinds not listed in `kind_weights` get weight 1.0 — they're
    not suppressed, just unweighted."""
    from trajectory.storage import insert_career_entry, retrieve_relevant_entries

    _seed(insert_career_entry(_entry(
        "proj", "project_note",
        "Ran an A/B test for ranking — lifted CTR 12%.",
    )))

    hits = _seed(retrieve_relevant_entries(
        user_id="u1",
        query_text="A/B test ranking",
        k=3,
        kind_weights={"star_polish": 2.0},  # proj's kind NOT in weights
    ))
    # proj should still come back (weight=1.0 fallback, not 0).
    assert any(h.entry_id == "proj" for h in hits)


def test_default_constant_is_exported(isolated_storage):
    """Module-level STAR_BOOST_KINDS is the single source of truth for
    generator callers."""
    from trajectory.storage import STAR_BOOST_KINDS

    assert STAR_BOOST_KINDS["star_polish"] == 1.5
    assert STAR_BOOST_KINDS["qa_answer"] == 1.2
    # cv_bullet deliberately absent → defaults to 1.0 at call time.
    assert "cv_bullet" not in STAR_BOOST_KINDS


# ---------------------------------------------------------------------------
# Kind-filtered search forwards the weights too
# ---------------------------------------------------------------------------


def test_search_career_entries_semantic_accepts_kind_weights(isolated_storage):
    from trajectory.storage import (
        insert_career_entry,
        search_career_entries_semantic,
    )

    _seed(insert_career_entry(_entry(
        "polish", "star_polish",
        "Led migration from monolith to microservices.",
    )))
    _seed(insert_career_entry(_entry(
        "bullet", "cv_bullet",
        "Led migration to microservices.",
    )))

    # ANY filter + weights → boost applies.
    hits = _seed(search_career_entries_semantic(
        user_id="u1",
        query="migration",
        kind_filter="ANY",
        top_k=2,
        kind_weights={"star_polish": 2.0, "qa_answer": 1.2},
    ))
    assert hits[0].entry_id == "polish"


# ---------------------------------------------------------------------------
# Empty store returns empty list (doesn't crash)
# ---------------------------------------------------------------------------


def test_retrieval_on_empty_index_returns_empty(isolated_storage):
    from trajectory.storage import retrieve_relevant_entries

    hits = _seed(retrieve_relevant_entries(
        user_id="u1", query_text="anything",
        kind_weights={"star_polish": 2.0},
    ))
    assert hits == []
