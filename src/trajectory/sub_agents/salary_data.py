"""Phase 1 — Salary Signals fetcher.

Data priority:
  1. ASHE (ONS) parquet — government ground truth for UK annual earnings
     Tries soc4_region → soc2_region → soc2_national fallback chain.
  2. Posted JD band — from ExtractedJobDescription.salary_band if present.
  3. python-jobspy aggregated postings — tertiary, sampled from live listings.

No RapidAPI. No Glassdoor/Levels.fyi API. Open-source-compatible only.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from ..config import settings
from ..schemas import (
    AggregatedPostings,
    AshePercentiles,
    Citation,
    PostedBand,
    SalarySignals,
)

logger = logging.getLogger(__name__)

_PROCESSED = settings.data_dir / "processed"

# ASHE table file names produced by scripts/fetch_gov_data.py
_ASHE_SOC4_REGION = _PROCESSED / "ashe_soc4_region.parquet"
_ASHE_SOC2_REGION = _PROCESSED / "ashe_soc2_region.parquet"
_ASHE_SOC2_NATIONAL = _PROCESSED / "ashe_soc2_national.parquet"

_ASHE_YEAR = 2024  # update when ONS releases new tables


# ---------------------------------------------------------------------------
# ASHE lookup
# ---------------------------------------------------------------------------


def _load_parquet(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return None


def _lookup_ashe(soc_code: str, region: str) -> Optional[AshePercentiles]:
    """Try SOC4×region → SOC2×region → SOC2×national, return first hit."""
    soc2 = soc_code[:2] if len(soc_code) >= 2 else soc_code

    # Tier 1: SOC 4-digit × region
    df = _load_parquet(_ASHE_SOC4_REGION)
    if df is not None:
        row = df[
            (df["soc_code"].astype(str) == str(soc_code))
            & (df["region"].str.lower() == region.lower())
        ]
        if not row.empty:
            r = row.iloc[0]
            return AshePercentiles(
                granularity="soc4_region",
                soc_code=str(soc_code),
                region=region,
                p10=_safe_int(r, "p10"),
                p25=_safe_int(r, "p25"),
                p50=_safe_int(r, "p50"),
                p75=_safe_int(r, "p75"),
                p90=_safe_int(r, "p90"),
                sample_year=int(r.get("sample_year", _ASHE_YEAR)),
            )

    # Tier 2: SOC 2-digit × region
    df = _load_parquet(_ASHE_SOC2_REGION)
    if df is not None:
        row = df[
            (df["soc_code"].astype(str) == str(soc2))
            & (df["region"].str.lower() == region.lower())
        ]
        if not row.empty:
            r = row.iloc[0]
            return AshePercentiles(
                granularity="soc2_region",
                soc_code=str(soc2),
                region=region,
                p10=_safe_int(r, "p10"),
                p25=_safe_int(r, "p25"),
                p50=_safe_int(r, "p50"),
                p75=_safe_int(r, "p75"),
                p90=_safe_int(r, "p90"),
                sample_year=int(r.get("sample_year", _ASHE_YEAR)),
            )

    # Tier 3: SOC 2-digit national
    df = _load_parquet(_ASHE_SOC2_NATIONAL)
    if df is not None:
        row = df[df["soc_code"].astype(str) == str(soc2)]
        if not row.empty:
            r = row.iloc[0]
            return AshePercentiles(
                granularity="soc2_national",
                soc_code=str(soc2),
                region=None,
                p10=_safe_int(r, "p10"),
                p25=_safe_int(r, "p25"),
                p50=_safe_int(r, "p50"),
                p75=_safe_int(r, "p75"),
                p90=_safe_int(r, "p90"),
                sample_year=int(r.get("sample_year", _ASHE_YEAR)),
            )

    return None


def _safe_int(row, col: str) -> Optional[int]:
    val = row.get(col)
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# python-jobspy aggregation (tertiary)
# ---------------------------------------------------------------------------


async def _aggregate_postings(role: str, location: str) -> Optional[AggregatedPostings]:
    try:
        from jobspy import scrape_jobs  # type: ignore[import]

        # scrape_jobs is fully synchronous (httpx + parsing); offload to a
        # worker thread so the event loop is not blocked for the duration
        # of the network round-trips.
        jobs = await asyncio.to_thread(
            scrape_jobs,
            site_name=["indeed", "linkedin"],
            search_term=role,
            location=location,
            country_indeed="UK",
            results_wanted=20,
            hours_old=720,
        )
        if jobs is None or jobs.empty:
            return None

        salaries = []
        urls: list[str] = []
        for _, row in jobs.iterrows():
            min_s = row.get("min_amount")
            max_s = row.get("max_amount")
            if min_s and max_s:
                # Convert hourly/daily to annual
                interval = str(row.get("interval", "yearly")).lower()
                if interval in ("hourly", "hour"):
                    min_s, max_s = min_s * 52 * 37.5, max_s * 52 * 37.5
                elif interval in ("daily", "day"):
                    min_s, max_s = min_s * 52 * 5, max_s * 52 * 5
                salaries.append((min_s + max_s) / 2)
            job_url = row.get("job_url") or row.get("url") or ""
            if job_url:
                urls.append(str(job_url))

        if not salaries:
            return None

        salaries.sort()
        n = len(salaries)
        p25 = int(salaries[int(n * 0.25)])
        p50 = int(salaries[int(n * 0.50)])
        p75 = int(salaries[int(n * 0.75)])
        return AggregatedPostings(
            listings_count=n,
            p25_gbp=p25,
            p50_gbp=p50,
            p75_gbp=p75,
            sample_urls=urls[:5],
        )
    except Exception as exc:
        logger.info("jobspy aggregation failed (non-fatal): %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


async def fetch(
    role: str,
    location: str,
    soc_code: str,
    posted_band: dict | None = None,
) -> SalarySignals:
    """Fetch salary signals for a role.

    Args:
        role: Job title for jobspy search.
        location: Location string (e.g. "London").
        soc_code: SOC 2020 4-digit code for ASHE lookup.
        posted_band: Raw salary_band dict from ExtractedJobDescription if present.
    """
    sources_consulted: list[str] = []
    citations: list[Citation] = []

    # 1. ASHE lookup (parquet read + pandas filter — offload to worker)
    ashe = await asyncio.to_thread(_lookup_ashe, soc_code, location)
    if ashe is not None:
        sources_consulted.append(f"ashe_{ashe.granularity}")
        citations.append(
            Citation(
                kind="gov_data",
                data_field=f"ashe.{ashe.granularity}.{soc_code}.p50",
                data_value=str(ashe.p50) if ashe.p50 else "unknown",
            )
        )

    # 2. Posted band from JD
    parsed_band: Optional[PostedBand] = None
    if posted_band:
        try:
            min_v = int(posted_band.get("min") or posted_band.get("min_gbp", 0))
            max_v = int(posted_band.get("max") or posted_band.get("max_gbp", 0))
            period_raw = str(posted_band.get("period", "annual")).lower()
            period = period_raw if period_raw in ("annual", "hourly", "daily") else "annual"
            source_url = str(posted_band.get("source_url", ""))
            snippet = str(posted_band.get("verbatim_snippet", f"£{min_v:,} - £{max_v:,}"))
            if min_v and max_v:
                parsed_band = PostedBand(
                    min_gbp=min_v,
                    max_gbp=max_v,
                    period=period,
                    source_url=source_url,
                    verbatim_snippet=snippet,
                )
                sources_consulted.append("posted_jd")
                if source_url:
                    citations.append(
                        Citation(
                            kind="url_snippet",
                            url=source_url,
                            verbatim_snippet=snippet,
                        )
                    )
        except Exception as exc:
            logger.debug("Could not parse posted_band dict: %s", exc)

    # 3. python-jobspy aggregation (tertiary, best-effort)
    agg = await _aggregate_postings(role=role, location=location)
    if agg is not None:
        sources_consulted.append("jobspy_aggregation")

    return SalarySignals(
        ashe=ashe,
        posted_band=parsed_band,
        aggregated_postings=agg,
        sources_consulted=sources_consulted,
        data_citations=citations,
    )
