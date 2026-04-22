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

import logging
import threading
from datetime import date, datetime
from typing import Optional

from ..config import settings
from ..schemas import SponsorStatus

logger = logging.getLogger(__name__)


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

    return {
        "name": pick("organisation name", "organisation_name", "name"),
        "rating": pick("rating", "tier rating", "tier_rating"),
        "routes": pick("route", "routes"),
        "last_updated": pick("last updated", "last_updated", "date"),
    }


def _map_status(rating: str) -> str:
    r = (rating or "").lower()
    if "suspend" in r:
        return "SUSPENDED"
    if r.startswith("b"):
        return "B_RATED"
    if r.startswith("a"):
        return "LISTED"
    return "LISTED"  # conservative default


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


async def lookup(company_name: str) -> SponsorStatus:
    try:
        df = _load_df()
    except FileNotFoundError as e:
        logger.error("%s", e)
        # Fail-safe: without the register we cannot verify — NOT_LISTED is
        # the conservative outcome, and the verdict agent will block.
        return SponsorStatus(status="NOT_LISTED", matched_name=None)

    from rapidfuzz import process, fuzz

    cols = _columns(df)
    name_col = cols["name"]
    rating_col = cols["rating"]
    routes_col = cols["routes"]

    if name_col is None:
        logger.error("Sponsor Register parquet missing expected name column.")
        return SponsorStatus(status="NOT_LISTED", matched_name=None)

    names: list[str] = df[name_col].astype(str).tolist()
    # process.extractOne returns (choice, score, index)
    match = process.extractOne(
        company_name, names, scorer=fuzz.WRatio, score_cutoff=_FUZZY_THRESHOLD
    )
    if not match:
        return SponsorStatus(status="NOT_LISTED", matched_name=None)

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
    )
