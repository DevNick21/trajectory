"""Application tracker API.

  - GET  /api/applications          — list user's applications + status

The tracker is the user-visible "what's happening with all the roles
I forwarded" view. Each row is 1:1 with a forward_job session; status
moves through the lifecycle as the user reports outcomes from any
surface. Source of truth: `application_tracker` table.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ...notifications import (
    ApplicationRecord,
    ApplicationStatus,
    list_applications,
)
from ...schemas import UserProfile
from ..dependencies import get_current_user

router = APIRouter()


class ApplicationListResponse(BaseModel):
    applications: list[ApplicationRecord]


@router.get("/applications", response_model=ApplicationListResponse)
async def get_applications(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    user: UserProfile = Depends(get_current_user),
) -> ApplicationListResponse:
    """List applications for the current user. Optional status filter
    is a comma-separated list (e.g. `?status=applied,offer_received`)."""
    statuses: Optional[list[ApplicationStatus]] = None
    if status_filter:
        raw = [s.strip() for s in status_filter.split(",") if s.strip()]
        # Static narrow: trust the Literal type to catch typos downstream;
        # invalid statuses just produce an empty result set since they
        # never match a stored row.
        statuses = raw  # type: ignore[assignment]
    apps = await list_applications(
        user_id=user.user_id, status_in=statuses, limit=limit,
    )
    return ApplicationListResponse(applications=apps)
