"""Seed three project notes (Pluck, Betfred, Venco) so the CV
generator has distinct sources to cite for the session-pack.mp4 take.

Uses the official `insert_career_entry` so:
  - SQLite row is inserted into `career_entries`
  - 384-dim embedding is computed via sentence-transformers
  - FAISS index is updated and persisted

Without the FAISS update, the CV agent's `retrieve_relevant_entries`
call won't find these rows and the multi-card ring jump still
won't work — even though the entries appear in the CareerHistory
left pane. Both surfaces have to know about the row.

Idempotent: re-running detects existing entries by `raw_text` match
and skips. Safe to run multiple times.

Usage:
    DEMO_USER_ID="<your-id>" python scripts/seed_career_entries.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

# Ensure src/ is on the path so we can import the package without install.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from trajectory.schemas import CareerEntry  # noqa: E402
from trajectory.storage import (  # noqa: E402
    get_all_career_entries_for_user,
    insert_career_entry,
)

# Three real project narratives. Kind = project_note (granular work
# experience entries, vs the existing "conversation" career-narrative).
# CV bullets generated from these will cite them via career_entry IDs;
# clicking each bullet rings the corresponding card on the left pane.
ENTRIES: list[dict[str, str]] = [
    {
        "kind": "project_note",
        "raw_text": (
            "Built the autonomous agentic scraping pipeline with "
            "self-healing schemas at Pluck (then Valae). The core problem "
            "was brittle data collection — they needed structured product "
            "data from dozens of e-commerce sites and the existing approach "
            "was a team manually checking pages every time a scraper broke. "
            "Every DOM change cost someone a morning. I built the pipeline "
            "around LangChain agents and Playwright, but the interesting "
            "part wasn't the scraping — it was the self-healing layer. "
            "When extraction failed validation, instead of crashing, the "
            "system passed the failed HTML to an LLM that re-inferred the "
            "schema, mapped it back to our internal types, and logged the "
            "change for human review. So a site changing its price markup "
            "from a <span> to a <div data-price> no longer broke anything "
            "— the agent adapted and kept going. Production safeguards "
            "mattered as much as the cleverness: token-bucket rate "
            "limiting, exponential backoff, modular API wrappers so we "
            "could swap OpenAI for Claude (which I did, cutting roughly "
            "80% of the cost by moving the lighter inference work to "
            "Haiku). Took the manual data ops job from roughly 40 hours a "
            "week to under two."
        ),
    },
    {
        "kind": "project_note",
        "raw_text": (
            "Handwriting classifier for compliance flagging at Betfred — "
            "built, demoed, didn't get adopted. Betfred has a paper-based "
            "betting slip flow, and compliance flagging was entirely "
            "manual. I built an EfficientNet-B0 classifier on slip "
            "handwriting, hit 80.8% accuracy overall and 100% on "
            "high-confidence predictions (the threshold is what made it "
            "viable — low-confidence ones go to a human, which is the "
            "right outcome anyway). Wrapped it with a C#/.NET 8 service "
            "for the existing till stack and a Python inference layer "
            "because I wasn't going to fight ONNX export for an MVP. The "
            "handwriting tags fed into a Smart Customer Behaviour "
            "Tracking system that flagged betting pattern anomalies — "
            "frequency, stake escalation, slip clustering. Demoed it to "
            "stakeholders, got real engagement, then it stalled at the "
            "'who owns this in production' question. The honest framing "
            "is: I built and demonstrated it. It wasn't formally adopted. "
            "The technical work stands; the org adoption didn't follow. "
            "Lesson learned about building POCs without a sponsor on the "
            "operations side, which I'm carrying forward."
        ),
    },
    {
        "kind": "project_note",
        "raw_text": (
            "Analytics engineering for credit risk at Venco — turning "
            "messy ledgers into something modellable. Venco's core data "
            "was service charge ledgers across estates — thousands of "
            "residents, irregular payment cadences, inconsistent "
            "categorisation across property managers. The job was to make "
            "this modellable for credit risk scoring, which meant the "
            "unglamorous work first: schema reconciliation across estates "
            "that had been onboarded at different times with different "
            "conventions, deduplication of resident records where the "
            "same person appeared three times under variant spellings, "
            "and rebuilding payment histories where late entries had "
            "been backfilled inconsistently. Once the substrate was "
            "clean I built the actual scoring features — payment "
            "regularity, arrears velocity, seasonality-adjusted "
            "defaults. Pandas-heavy, with the heavier aggregations "
            "pushed to SQL because pandas chokes on group-bys at that "
            "size. The thing I took away from this role is that the "
            "modelling is the easy part. Eighty percent of the work was "
            "making the data trustworthy enough that anyone would "
            "believe the score. That framing has stuck with me on every "
            "data project since."
        ),
    },
]


async def main() -> int:
    user_id = os.environ.get("DEMO_USER_ID", "").strip()
    if not user_id:
        print("ERROR: set DEMO_USER_ID in your environment first.", file=sys.stderr)
        return 1

    existing = await get_all_career_entries_for_user(user_id)
    existing_texts = {e.raw_text for e in existing}

    inserted = 0
    skipped = 0
    now = datetime.now(timezone.utc)

    for spec in ENTRIES:
        if spec["raw_text"] in existing_texts:
            skipped += 1
            continue
        entry = CareerEntry(
            entry_id=str(uuid.uuid4()),
            user_id=user_id,
            kind=spec["kind"],  # type: ignore[arg-type]
            raw_text=spec["raw_text"],
            structured=None,
            source_session_id=None,
            embedding=None,  # insert_career_entry computes this
            created_at=now,
        )
        await insert_career_entry(entry)
        inserted += 1
        print(f"  + {entry.kind}: {entry.raw_text[:60]}…")

    print(f"\nInserted: {inserted}  |  Skipped (already present): {skipped}")
    print(
        "\nNext: regenerate the Capital on Tap CV. The bullets should now "
        "cite these entries via FAISS retrieval. Verify with the "
        "console.table debug output in CVPreview."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
