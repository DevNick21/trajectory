"""GET /api/career-entries — current user's career-store rows.

Powers the Deep Work workspace (left pane "My Career History"). Each
generated CV bullet cites entries by ``entry_id``; the frontend uses
that to highlight the source entry on the left when the user clicks a
bullet on the right. Filtering by ``kind`` is a query param so the UI
can show only ``cv_bullet`` + ``conversation`` (the "real" career
history) while still being able to fetch motivations / deal-breakers
when an ``entry_id`` resolves to one of those.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ...schemas import CareerEntry
from ...storage import get_all_career_entries_for_user
from ..dependencies import get_current_user_id

router = APIRouter()


class CareerEntriesResponse(BaseModel):
    entries: list[CareerEntry]


@router.get("/career-entries", response_model=CareerEntriesResponse)
async def list_career_entries(
    kinds: Optional[str] = Query(
        None,
        description=(
            "Comma-separated CareerEntry.kind values to filter by. "
            "Omit to return all kinds."
        ),
    ),
    user_id: str = Depends(get_current_user_id),
) -> CareerEntriesResponse:
    entries = await get_all_career_entries_for_user(user_id)

    if kinds:
        wanted = {k.strip() for k in kinds.split(",") if k.strip()}
        entries = [e for e in entries if e.kind in wanted]

    # Strip embeddings before serialising — large floats list, not
    # useful to the web UI, and saves bandwidth.
    for e in entries:
        e.embedding = None

    return CareerEntriesResponse(entries=entries)
