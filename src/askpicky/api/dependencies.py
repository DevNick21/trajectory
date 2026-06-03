"""FastAPI dependency providers.

`get_storage` reads from `app.state` (set up by the lifespan). Identity is
resolved through the configured auth mode: local OSS/dev can use demo identity,
while hosted V2 uses Supabase bearer JWTs.

`get_current_user` raises 404 when the authenticated user has not completed
onboarding; the frontend interprets this as "redirect to /onboarding" rather
than treating it as a server error.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request, status

from ..config import settings
from ..ratelimit import RateLimiter, intent_to_category
from ..schemas import UserProfile
from ..storage import Storage
from .auth import resolve_identity


# Module-level singleton — shared across requests in one FastAPI process.
# Lifetime matches the app process (see ratelimit.py doc comment).
_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _rate_limiter


def rate_limit(intent: str) -> Any:
    """Return a FastAPI dependency that throttles `intent` per-user.

    Usage: `@router.post(..., dependencies=[Depends(rate_limit("draft_cv"))])`
    No-op when `settings.enforce_rate_limit` is False so dev/demo
    runs stay unthrottled.
    """

    async def _dep(
        user_id: str = Depends(get_current_user_id),
        storage: Storage = Depends(get_storage),
        limiter: RateLimiter = Depends(get_rate_limiter),
    ) -> None:
        if settings.enforce_rate_limit:
            decision = limiter.check(user_id, intent)
            if not decision.allowed:
                retry_after = max(1, int(decision.retry_after_s + 0.5))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "code": "rate_limited",
                        "intent": intent,
                        "category": decision.category,
                        "retry_after_s": retry_after,
                    },
                    headers={"Retry-After": str(retry_after)},
                )
        if settings.enforce_hosted_quotas:
            result = await storage.record_quota_usage(
                user_id=user_id,
                category=intent_to_category(intent),
                units=1,
            )
            if not result["allowed"]:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "code": "quota_exceeded",
                        "intent": intent,
                        "category": result["category"],
                        "period": result["period"],
                        "limit": result["limit"],
                        "used": result["used"],
                    },
                )

    return _dep


def get_storage(request: Request) -> Storage:
    """Return the Storage instance from app.state.

    Bound to the FastAPI app's lifetime by the lifespan in app.py.
    """
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        # Should never happen in production — would mean lifespan didn't
        # run. Surface as 503 so the frontend retries rather than crashes.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="storage not initialised",
        )
    return storage


def get_current_user_id(request: Request) -> str:
    """Return the authenticated AskPicky user id.

    Demo mode returns the configured local dev user. Hosted mode requires a
    valid Supabase bearer JWT and maps the token `sub` to `user_id`.
    """
    return resolve_identity(request).user_id


async def get_current_user(
    user_id: str = Depends(get_current_user_id),
    storage: Storage = Depends(get_storage),
) -> UserProfile:
    """Resolve the authenticated user's profile.

    Raises 404 with a `code: profile_not_found` body so the frontend
    can route the visitor to the onboarding wizard rather than show
    a generic error page.
    """
    profile = await storage.get_user_profile(user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "profile_not_found",
                "message": "Profile not found — complete onboarding first.",
            },
        )
    return profile
