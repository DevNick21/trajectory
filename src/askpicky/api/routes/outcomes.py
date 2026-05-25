"""Outcome reporting (ASKPICKY.md §6 Layer 6 — the data network flywheel).

  - POST /api/sessions/{id}/outcome  — record what happened after applying

The outcome reporter + tracker via `mark_outcome()` is a single source
of truth. Outcomes never gate any other feature. Reporting is always free
(ASKPICKY.md §7 "Limits never gate outcome reporting").
"""

from __future__ import annotations

import logging
from typing import Literal, Optional, cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ...memory.recorder import record_application_outcome
from ...notifications import (
    ApplicationStatus,
    cancel_notifications_for_session,
    update_application_status,
)
from ...schemas import Session, UserProfile
from ...storage import Storage
from ..dependencies import get_current_user, get_storage

logger = logging.getLogger(__name__)
router = APIRouter()


OutcomeKind = Literal[
    "applied",
    "no_response",
    "rejected_screen",
    "rejected_interview",
    "rejected_offer",
    "offer_received",
    "offer_accepted",
    "offer_declined",
]


class OutcomeRequest(BaseModel):
    outcome: OutcomeKind
    notes: Optional[str] = Field(default=None, max_length=2000)


class OutcomeResponse(BaseModel):
    ok: bool = True
    session_id: str
    outcome: OutcomeKind


async def mark_outcome(
    *,
    user: UserProfile,
    session: Session,
    outcome: OutcomeKind,
    notes: Optional[str] = None,
) -> None:
    """Cross-surface single entry point for recording an outcome.

    Wires together the recorder (network/memory), the application
    tracker state machine, and the notifications queue.     Called by:
      - this HTTP route (web)
      - email link landing → web route → here

    Idempotent on (session_id, outcome) — re-reporting the same
    outcome is allowed and a no-op for the tracker.
    """
    bundle = session.research_bundle if hasattr(session, "research_bundle") else None
    company_name = (
        bundle.company_research.company_name
        if bundle and bundle.company_research
        else "Unknown"
    )
    role_title = (
        bundle.extracted_jd.role_title
        if bundle and bundle.extracted_jd
        else "Unknown"
    )

    await record_application_outcome(
        user_id=user.user_id,
        session_id=session.session_id,
        company_name=company_name,
        role_title=role_title,
        outcome=outcome,
        notes=notes,
    )
    await update_application_status(
        session_id=session.session_id,
        new_status=cast(ApplicationStatus, outcome),
        notes=notes,
    )
    cancelled = await cancel_notifications_for_session(
        session_id=session.session_id, user_id=user.user_id,
    )
    logger.info(
        "Outcome recorded: session=%s outcome=%s cancelled_nudges=%d",
        session.session_id, outcome, cancelled,
    )


@router.post(
    "/sessions/{session_id}/outcome",
    response_model=OutcomeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def record_outcome(
    session_id: str,
    body: OutcomeRequest,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> OutcomeResponse:
    """Record the terminal outcome of an application.

    Ownership-gated: 404 covers both "session not found" and "not yours"
    so an attacker cannot enumerate session ids.
    """
    session = await storage.get_session(session_id)
    if session is None or session.user_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )

    await mark_outcome(
        user=user, session=session, outcome=body.outcome, notes=body.notes,
    )
    return OutcomeResponse(
        ok=True, session_id=session_id, outcome=body.outcome,
    )
