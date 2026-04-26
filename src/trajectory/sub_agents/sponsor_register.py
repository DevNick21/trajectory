"""Phase 1 — Sponsor Register lookup.

Pandas lookup against `data/processed/sponsor_register.parquet`. Fuzzy
name match at 92% rapidfuzz ratio, configurable via `_FUZZY_THRESHOLD`.

Returned `SponsorStatus.status`:
  - LISTED      -> company present, rating A
  - B_RATED     -> rating B
  - SUSPENDED   -> rating contains "suspended"
  - NOT_LISTED  -> no plausible match above threshold
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import date, datetime
from typing import Optional

from ..config import settings
from ..data_freshness import is_stale
from ..schemas import SponsorStatus

logger = logging.getLogger(__name__)

# Sponsor Register is updated daily by the Home Office. 14 days is
# tight enough to catch rating changes that matter for visa users,
# loose enough to tolerate a weekly refresh cron.
_STALE_WINDOW_DAYS = 14


_FUZZY_THRESHOLD = 92

_df = None
_df_lock = threading.Lock()


def _parquet_path():
    return settings.data_dir / "processed" / "sponsor_register.parquet"


def _load_df():
    global _df
    if _df is not None:
        return _df
    with _df_lock:
        if _df is not None:
            return _df
        path = _parquet_path()
        if not path.exists():
            raise FileNotFoundError(
                f"Sponsor Register parquet not found at {path}. "
                "Run `python scripts/fetch_gov_data.py` first."
            )
        import pandas as pd

        _df = pd.read_parquet(path)
    return _df


def _columns(df) -> dict:
    """Normalise to a known set of columns. The gov CSV column names
    shift periodically; we pick whichever exists.
    """
    lowered = {c.lower(): c for c in df.columns}

    def pick(*candidates: str) -> Optional[str]:
        for cand in candidates:
            if cand in lowered:
                return lowered[cand]
        return None

    # Column names rotate with every Home Office publication — the
    # current (2026-04) CSV uses "Type & Rating" for the rating field.
    return {
        "name": pick("organisation name", "organisation_name", "name"),
        "rating": pick(
            "type & rating", "type and rating",
            "rating", "tier rating", "tier_rating",
        ),
        "routes": pick("route", "routes"),
        "last_updated": pick("last updated", "last_updated", "date"),
    }


def _map_status(rating: str) -> str:
    """Map the Home Office "Type & Rating" cell onto our status enum.

    Observed values in the register (top 10 of ~140k rows):
      Worker (A rating)          — the canonical licensed sponsor
      Temporary Worker (A rating)
      Worker (UK Expansion Worker: Provisional )
      Worker (B rating)
      Worker (A (Premium))       — still an A-rated sponsor
      Temporary Worker (B rating)
      Worker (A (SME+))
      Temporary Worker (A (SME+))
      Temporary Worker (A (Premium))

    Previous "startswith" logic matched the leading "Worker"/"Temporary"
    literal and fell through to NOT_LISTED for every sponsor. Search the
    parenthesised rating token instead.
    """
    import re as _re

    r = (rating or "").lower()
    if "suspend" in r:
        return "SUSPENDED"
    # Pull the rating letter out of "(A rating)" / "(B rating)" / "(A (Premium))".
    m = _re.search(r"\(\s*([ab])\b", r)
    if m:
        return "B_RATED" if m.group(1) == "b" else "LISTED"
    # "UK Expansion Worker: Provisional" — treat as LISTED for our
    # purposes (company IS on the register and can sponsor).
    if "provisional" in r or "expansion" in r:
        return "LISTED"
    # Unrecognised rating: flag NOT_LISTED so the verdict agent treats
    # this as a hard blocker rather than greenlighting a visa holder
    # against unknown status.
    return "NOT_LISTED"


def _last_updated(df, col: Optional[str]) -> Optional[date]:
    if col is None:
        return None
    try:
        val = df[col].dropna().iloc[0]
        if isinstance(val, str):
            return datetime.strptime(val[:10], "%Y-%m-%d").date()
    except Exception:
        return None
    return None


def _lookup_sync(company_name: str) -> SponsorStatus:
    try:
        df = _load_df()
    except FileNotFoundError as e:
        logger.error("%s", e)
        # Fail-safe: without the register we cannot verify — NOT_LISTED is
        # the conservative outcome, and the verdict agent will block.
        return SponsorStatus(
            status="NOT_LISTED",
            matched_name=None,
            source_status=_freshness_status(),
        )

    from rapidfuzz import process, fuzz

    cols = _columns(df)
    name_col = cols["name"]
    rating_col = cols["rating"]
    routes_col = cols["routes"]

    if name_col is None:
        logger.error("Sponsor Register parquet missing expected name column.")
        return SponsorStatus(
            status="NOT_LISTED",
            matched_name=None,
            source_status=_freshness_status(),
        )

    names: list[str] = df[name_col].astype(str).tolist()
    # process.extractOne returns (choice, score, index)
    match = process.extractOne(
        company_name, names, scorer=fuzz.WRatio, score_cutoff=_FUZZY_THRESHOLD
    )
    if not match:
        return SponsorStatus(
            status="NOT_LISTED",
            matched_name=None,
            source_status=_freshness_status(),
        )

    matched_name, _score, idx = match
    row = df.iloc[idx]

    rating = str(row[rating_col]) if rating_col else ""
    routes_raw = str(row[routes_col]) if routes_col else ""
    visa_routes = [r.strip() for r in routes_raw.split(",") if r.strip()]

    return SponsorStatus(
        status=_map_status(rating),
        matched_name=matched_name,
        rating=rating or None,
        visa_routes=visa_routes,
        last_register_update=_last_updated(df, cols["last_updated"]),
        source_status=_freshness_status(),
    )


def _freshness_status() -> str:
    """D3: STALE when the parquet sidecar is missing or older than the
    freshness window. OK otherwise."""
    if is_stale(_parquet_path(), window_days=_STALE_WINDOW_DAYS):
        logger.warning(
            "sponsor_register parquet is stale or has no freshness sidecar; "
            "verdict will mark source_status=STALE."
        )
        return "STALE"
    return "OK"


async def lookup(company_name: str) -> SponsorStatus:
    # The lookup is a parquet load + pandas filter + rapidfuzz scan — all
    # CPU-bound and synchronous. Offload to a thread so the event loop is
    # not blocked while the register is scanned.
    return await asyncio.to_thread(_lookup_sync, company_name)
