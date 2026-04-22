"""Phase 1 — Salary Signals fetcher.

Combines:
  - posted_band: from ExtractedJobDescription.salary_band (if present)
  - glassdoor_range, levels_fyi_range: via RapidAPI (skeleton placeholders)
  - market_p10 / p50 / p90: computed from available sources

Returns SalarySignals with `sources_consulted` always populated so the
verdict agent can reason about coverage.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from ..config import settings
from ..schemas import Citation, ExtractedJobDescription, SalarySignals

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0


# ---------------------------------------------------------------------------
# External fetches (skeleton placeholders — return None on failure)
# ---------------------------------------------------------------------------


async def _glassdoor_range(role: str, location: str) -> Optional[dict]:
    if not settings.rapidapi_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://glassdoor-real-time.p.rapidapi.com/salaries/search",
                headers={
                    "x-rapidapi-key": settings.rapidapi_key,
                    "x-rapidapi-host": "glassdoor-real-time.p.rapidapi.com",
                },
                params={"role": role, "location": location},
            )
            if resp.status_code != 200:
                return None
            _ = resp.json()
    except Exception as e:
        logger.warning("Glassdoor salary fetch failed: %s", e)
    return None


async def _levels_fyi_range(role: str, location: str) -> Optional[dict]:
    if not settings.rapidapi_key:
        return None
    # Skeleton placeholder — left for a follow-up when a Levels.fyi RapidAPI
    # provider is chosen.
    return None


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


async def fetch(
    role: str,
    location: str,
    company: Optional[str] = None,
    jd: Optional[ExtractedJobDescription] = None,
) -> SalarySignals:
    sources_consulted: list[str] = []
    citations: list[Citation] = []

    posted_band: Optional[dict] = None
    if jd is not None and jd.salary_band:
        posted_band = dict(jd.salary_band)
        sources_consulted.append("posted_band")

    glassdoor_range = await _glassdoor_range(role, location)
    if glassdoor_range is not None:
        sources_consulted.append("glassdoor")

    levels_range = await _levels_fyi_range(role, location)
    if levels_range is not None:
        sources_consulted.append("levels_fyi")

    # Percentile computation: when upstream providers return ranges, fold
    # them into crude p10/p50/p90. Skeleton leaves this null until a
    # provider actually returns numbers.
    p10 = p50 = p90 = None

    return SalarySignals(
        posted_band=posted_band,
        glassdoor_range=glassdoor_range,
        levels_fyi_range=levels_range,
        market_p10=p10,
        market_p50=p50,
        market_p90=p90,
        sources_consulted=sources_consulted,
        data_citations=citations,
    )
