"""Smoke test — FAISS retrieval over CareerEntry embeddings (no LLM).

Seeds a small set of CareerEntry rows, rebuilds the index, and checks
that a targeted query surfaces the semantically-relevant entry in the
top-k. Also exercises kind_weights by boosting `star_polish` entries.

Cost: $0 (local sentence-transformers embedding; first run pulls the
model weights, subsequent runs are a few seconds).
"""

from __future__ import annotations

import uuid

from ._common import (
    SmokeResult,
    now_utc_naive,
    prepare_environment,
    run_smoke,
)

NAME = "faiss_retrieval"
REQUIRES_LIVE_LLM = False


def _make_entry(kind: str, text: str, user_id: str):
    from askpicky.schemas import CareerEntry

    return CareerEntry(
        entry_id=str(uuid.uuid4()),
        user_id=user_id,
        kind=kind,
        raw_text=text,
        created_at=now_utc_naive(),
    )


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from askpicky.config import settings
    from askpicky import storage as storage_module
    from askpicky.storage import Storage

    settings.embedding_dim = 8

    def _vec(text: str) -> list[float]:
        lower = text.lower()
        return [
            1.0 if "latency" in lower or "p99" in lower else 0.0,
            1.0 if "postmortem" in lower or "incident" in lower else 0.0,
            1.0 if "python" in lower or "django" in lower else 0.0,
            1.0 if "payment" in lower or "kubernetes" in lower else 0.0,
            1.0 if "rust" in lower or "tui" in lower else 0.0,
            1.0 if "production" in lower else 0.0,
            1.0 if "debug" in lower or "regression" in lower else 0.0,
            0.1,
        ]

    async def _fake_embed(text: str) -> list[float]:
        return _vec(text)

    async def _fake_embed_batch(texts: list[str]) -> list[list[float]]:
        return [_vec(text) for text in texts]

    storage_module._embed = _fake_embed
    storage_module._embed_batch = _fake_embed_batch
    storage_module._faiss_index = None
    storage_module._faiss_id_map = []

    messages: list[str] = []
    failures: list[str] = []

    storage = Storage()
    await storage.initialise()

    user_id = "smoke_faiss_user"
    entries = [
        _make_entry("cv_bullet",
                    "Built a distributed payments pipeline on Kubernetes at 1M RPS.",
                    user_id),
        _make_entry("cv_bullet",
                    "Wrote a Django CMS for a publishing startup; 50k daily users.",
                    user_id),
        _make_entry("star_polish",
                    "Led an incident postmortem after a currency conversion regression "
                    "shipped. Reduced MTTR from 4h to 45m.",
                    user_id),
        _make_entry("project_note",
                    "Side project: a TUI mail client written in Rust.",
                    user_id),
        _make_entry("qa_answer",
                    "Described a time I cut p99 latency by 400ms through parallel "
                    "fan-out and in-memory caching.",
                    user_id),
    ]
    for e in entries:
        await storage.insert_career_entry(e)
    messages.append(f"seeded {len(entries)} career entries")

    # Targeted query — should surface the latency entry near the top.
    results = await storage.retrieve_relevant_entries(
        user_id=user_id,
        query="cutting tail latency in production systems",
        k=3,
    )
    if not results:
        failures.append("retrieve_relevant_entries returned no rows.")
    else:
        messages.append(
            "top-3 kinds: " + ", ".join(r.kind for r in results)
        )
        top_text = results[0].raw_text.lower()
        if "latency" not in top_text and "p99" not in top_text and "postmortem" not in top_text:
            failures.append(
                f"Top retrieval was unexpected for a latency query: {results[0].raw_text!r}"
            )

    # kind_weights boost — STAR polish should float to the top on a
    # generic query when weighted heavily.
    boosted = await storage.retrieve_relevant_entries(
        user_id=user_id,
        query="describe a time you debugged a tricky production issue",
        k=3,
        kind_weights={"star_polish": 3.0, "qa_answer": 2.0},
    )
    if not boosted:
        failures.append("weighted retrieve_relevant_entries returned no rows.")
    else:
        top_kinds = [r.kind for r in boosted]
        messages.append(f"weighted top-3 kinds: {top_kinds}")
        if "star_polish" not in top_kinds[:2] and "qa_answer" not in top_kinds[:2]:
            failures.append(
                "kind_weights did not push star_polish / qa_answer into top-2: "
                f"{top_kinds}"
            )

    await storage.close()
    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
