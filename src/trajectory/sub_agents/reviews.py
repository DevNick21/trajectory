"""Phase 1 — Glassdoor review excerpt fetcher via RapidAPI.

The red_flags detector consumes these. The schema is minimal and local
to this module (not promoted to schemas.py until the shape stabilises).
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from pydantic import BaseModel

from ..config import settings

logger = logging.getLogger(__name__)


class ReviewExcerpt(BaseModel):
    source: str
    rating: Optional[float] = None
    title: Optional[str] = None
    text: str
    url: Optional[str] = None


# RapidAPI Glassdoor provider (swap the host when a provider is confirmed).
_RAPIDAPI_HOST = "glassdoor-real-time.p.rapidapi.com"
_TIMEOUT = 15.0


async def fetch(company_name: str) -> list[ReviewExcerpt]:
    """Fetch up to ~10 recent review excerpts. Returns [] on any failure.

    Skeleton note: the exact RapidAPI provider shape varies. This function
    returns an empty list until wired to a concrete provider in a follow-up.
    """
    if not settings.rapidapi_key:
        logger.info("RAPIDAPI_KEY not set; skipping reviews.")
        return []

    headers = {
        "x-rapidapi-key": settings.rapidapi_key,
        "x-rapidapi-host": _RAPIDAPI_HOST,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"https://{_RAPIDAPI_HOST}/companies/search",
                headers=headers,
                params={"q": company_name},
            )
            if resp.status_code != 200:
                return []
            # Provider-specific payload shape — left as a no-op pending
            # provider confirmation. See PROCESS.md.
            _ = resp.json()
    except Exception as e:
        logger.warning("Glassdoor fetch failed for %r: %s", company_name, e)
        return []

    return []
