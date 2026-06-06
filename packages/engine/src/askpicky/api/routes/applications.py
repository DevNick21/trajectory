"""Application tracker API.

  - GET  /api/applications          — list user's applications + status
  - POST /api/applications/local    — save a pasted JD as a tracker row
  - PATCH /api/applications/{id}/status
                                      — update manual tracker status

The tracker is the user-visible "what's happening with all the roles"
view for forwarded jobs and local pasted job descriptions. Source of
truth: `application_tracker` table.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ...applications import (
    ApplicationRecord,
    ApplicationStatus,
    create_local_application_from_jd,
    list_applications,
    update_application_status,
)
from ..dependencies import get_current_user_id, rate_limit

router = APIRouter()


class ApplicationListResponse(BaseModel):
    applications: list[ApplicationRecord]


class LocalApplicationRequest(BaseModel):
    jd_text: str = Field(min_length=40, max_length=120_000)
    company_name: Optional[str] = Field(default=None, max_length=120)


class ApplicationResponse(BaseModel):
    application: ApplicationRecord


class ApplicationStatusRequest(BaseModel):
    status: ApplicationStatus
    notes: Optional[str] = Field(default=None, max_length=2000)


@router.get("/applications", response_model=ApplicationListResponse)
async def get_applications(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: str = Depends(get_current_user_id),
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
        user_id=user_id, status_in=statuses, limit=limit,
    )
    return ApplicationListResponse(applications=apps)


@router.post(
    "/applications/local",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("job_analysis"))],
)
async def save_local_application(
    body: LocalApplicationRequest,
    user_id: str = Depends(get_current_user_id),
) -> ApplicationResponse:
    """Save a pasted job description into the manual tracker."""
    application = await create_local_application_from_jd(
        user_id=user_id,
        jd_text=body.jd_text,
        company_name=body.company_name,
    )
    return ApplicationResponse(application=application)


@router.patch(
    "/applications/{session_id}/status",
    response_model=ApplicationResponse,
)
async def set_application_status(
    session_id: str,
    body: ApplicationStatusRequest,
    user_id: str = Depends(get_current_user_id),
) -> ApplicationResponse:
    """Update a manual tracker row owned by the current user."""
    application = await update_application_status(
        session_id=session_id,
        new_status=body.status,
        notes=body.notes,
        user_id=user_id,
    )
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        )
    return ApplicationResponse(application=application)
