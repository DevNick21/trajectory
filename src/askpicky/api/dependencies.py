"""FastAPI dependency providers.

`get_storage` reads from `app.state` (set up by the lifespan). The
identity providers (`get_current_user_id`, `get_current_user`) use
`settings.demo_user_id` since the API is single-user localhost
(ADR-001). Multi-user auth is post-hackathon scope.

`get_current_user` raises 404 when the demo user hasn't completed
onboarding — the frontend interprets this as "redirect to
/onboarding" rather than treating it as a server error.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from ..config import settings
from ..ratelimit import RateLimiter
from ..schemas import UserProfile
from ..storage import Storage


# Module-level singleton — shared across requests in one FastAPI process.
# Lifetime matches the app process (see ratelimit.py doc comment).
_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _rate_limiter


def rate_limit(intent: str):
    """Return a FastAPI dependency that throttles `intent` per-user.

    Usage: `@router.post(..., dependencies=[Depends(rate_limit("draft_cv"))])`
    No-op when `settings.enforce_rate_limit` is False so dev/demo
    runs stay unthrottled.
    """

    def _dep(
        user_id: str = Depends(get_current_user_id),
        limiter: RateLimiter = Depends(get_rate_limiter),
    ) -> None:
        if not settings.enforce_rate_limit:
            return
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


def get_current_user_id() -> str:
    """Return the configured demo user id.

    Single-user localhost only — both surfaces resolve to the same
    `user_profiles` row keyed by this value (MIGRATION_PLAN.md §3).
    """
    if not settings.demo_user_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "DEMO_USER_ID is not set. Add it to your .env "
                "(your Telegram numeric user id) before starting the API."
            ),
        )
    return settings.demo_user_id


async def get_current_user(
    user_id: str = Depends(get_current_user_id),
    storage: Storage = Depends(get_storage),
) -> UserProfile:
    """Resolve the demo user's profile.

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
