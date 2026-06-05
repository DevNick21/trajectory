"""Local privacy controls: export and hard delete."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ...privacy import (
    delete_application_data,
    delete_cv_data,
    export_user_data,
    hard_delete_user_data,
)
from ...schemas import UserProfile
from ..dependencies import get_current_user, rate_limit

router = APIRouter()


class PrivacyExportResponse(BaseModel):
    user_id: str
    data: dict[str, Any]


class PrivacyDeleteResponse(BaseModel):
    deleted: dict[str, int]


@router.get(
    "/privacy/export",
    response_model=PrivacyExportResponse,
    dependencies=[Depends(rate_limit("privacy_export"))],
)
async def export_privacy_data(
    include_raw: bool = Query(default=True),
    user: UserProfile = Depends(get_current_user),
) -> PrivacyExportResponse:
    return PrivacyExportResponse(
        user_id=user.user_id,
        data=await export_user_data(user_id=user.user_id, include_raw=include_raw),
    )


@router.delete(
    "/privacy/me",
    response_model=PrivacyDeleteResponse,
    dependencies=[Depends(rate_limit("privacy_delete"))],
)
async def delete_my_data(
    user: UserProfile = Depends(get_current_user),
) -> PrivacyDeleteResponse:
    return PrivacyDeleteResponse(
        deleted=await hard_delete_user_data(user_id=user.user_id),
    )


@router.delete(
    "/privacy/cv",
    response_model=PrivacyDeleteResponse,
    dependencies=[Depends(rate_limit("privacy_delete"))],
)
async def delete_my_cv_data(
    user: UserProfile = Depends(get_current_user),
) -> PrivacyDeleteResponse:
    return PrivacyDeleteResponse(
        deleted={"career_entries": await delete_cv_data(user_id=user.user_id)},
    )


@router.delete(
    "/privacy/applications/{session_id}",
    response_model=PrivacyDeleteResponse,
    dependencies=[Depends(rate_limit("privacy_delete"))],
)
async def delete_application(
    session_id: str,
    user: UserProfile = Depends(get_current_user),
) -> PrivacyDeleteResponse:
    return PrivacyDeleteResponse(
        deleted=await delete_application_data(
            user_id=user.user_id,
            session_id=session_id,
        ),
    )
