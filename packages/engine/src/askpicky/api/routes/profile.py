"""GET /api/profile — current user's UserProfile.

Returns 404 with `{"code": "profile_not_found"}` body when onboarding
hasn't completed (handled by `get_current_user`). The frontend uses
that signal to redirect to /onboarding rather than showing a generic
error.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...schemas import UserProfile
from ..dependencies import get_current_user

router = APIRouter()


@router.get("/profile", response_model=UserProfile)
async def get_profile(user: UserProfile = Depends(get_current_user)) -> UserProfile:
    return user
