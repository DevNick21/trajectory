"""Phase 1 — SOC Check.

Looks up Skilled Worker going rate for `jd.soc_code_guess`, computes any
shortfall against the offered salary, and decides new-entrant eligibility.

Parquet inputs (produced by `scripts/fetch_gov_data.py`):
  - data/processed/going_rates.parquet   (SOC -> annual going_rate_gbp,
                                          optional new_entrant_rate_gbp)
  - data/processed/soc_codes.parquet     (SOC -> title, appendix flag)

New-entrant eligibility heuristic (Home Office rules, simplified):
  - Graduate visa holder, OR
  - Under 26 (no DOB captured in UserProfile — fall back to route check), OR
  - Switching from student route within the last 2 years.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from ..config import settings
from ..schemas import ExtractedJobDescription, SocCheckResult, UserProfile

logger = logging.getLogger(__name__)


_going_df = None
_soc_df = None
_lock = threading.Lock()


def _load():
    global _going_df, _soc_df
    if _going_df is not None and _soc_df is not None:
        return _going_df, _soc_df
    with _lock:
        if _going_df is not None and _soc_df is not None:
            return _going_df, _soc_df

        import pandas as pd

        going_path = settings.data_dir / "processed" / "going_rates.parquet"
        soc_path = settings.data_dir / "processed" / "soc_codes.parquet"

        if not going_path.exists() or not soc_path.exists():
            raise FileNotFoundError(
                "Going rates or SOC codes parquet missing. Run "
                "`python scripts/fetch_gov_data.py` first."
            )

        _going_df = pd.read_parquet(going_path)
        _soc_df = pd.read_parquet(soc_path)
    return _going_df, _soc_df


def _pick_col(df, *candidates: str) -> Optional[str]:
    lowered = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand in lowered:
            return lowered[cand]
    return None


def _offered_salary(jd: ExtractedJobDescription) -> Optional[int]:
    if not jd.salary_band:
        return None
    # Use the minimum of the band — going-rate check is against the lowest
    # offer the employer would make.
    for key in ("min", "minimum", "lower", "from"):
        if key in jd.salary_band and jd.salary_band[key] is not None:
            try:
                return int(jd.salary_band[key])
            except (TypeError, ValueError):
                continue
    return None


def _new_entrant_eligible(user: UserProfile) -> bool:
    if user.user_type != "visa_holder":
        return False
    if user.visa_status is None:
        return False
    # Graduate visa holders are the canonical new-entrant population for
    # this product; `student` switchers also qualify per Home Office.
    if user.visa_status.route in {"graduate", "student"}:
        return True
    # Time-in-UK proxy: if the current visa expires within 12 months and
    # they were previously on the graduate route, they still count. The
    # profile doesn't track prior routes, so we are conservative.
    return False


async def verify(
    jd: ExtractedJobDescription,
    user: UserProfile,
) -> SocCheckResult:
    try:
        going_df, soc_df = _load()
    except FileNotFoundError as e:
        logger.error("%s", e)
        # Safe default: mark ineligible so the verdict agent blocks.
        return SocCheckResult(
            soc_code=jd.soc_code_guess,
            soc_title="unknown",
            on_appendix_skilled_occupations=False,
            below_threshold=True,
            new_entrant_eligible=False,
        )

    soc_code = str(jd.soc_code_guess).strip()
    soc_name_col = _pick_col(soc_df, "soc_code", "code")
    soc_title_col = _pick_col(soc_df, "title", "soc_title")
    appendix_col = _pick_col(soc_df, "on_appendix", "appendix", "eligible")

    going_code_col = _pick_col(going_df, "soc_code", "code")
    going_rate_col = _pick_col(going_df, "going_rate_gbp", "going_rate", "annual_rate")
    new_entrant_col = _pick_col(going_df, "new_entrant_rate_gbp", "new_entrant_rate")

    # SOC metadata.
    soc_title = "unknown"
    on_appendix = False
    if soc_name_col is not None:
        soc_rows = soc_df[soc_df[soc_name_col].astype(str) == soc_code]
        if len(soc_rows) > 0:
            if soc_title_col is not None:
                soc_title = str(soc_rows.iloc[0][soc_title_col])
            if appendix_col is not None:
                on_appendix = bool(soc_rows.iloc[0][appendix_col])

    # Going rates.
    going_rate: Optional[int] = None
    new_entrant_rate: Optional[int] = None
    if going_code_col is not None:
        rate_rows = going_df[going_df[going_code_col].astype(str) == soc_code]
        if len(rate_rows) > 0:
            if going_rate_col is not None:
                try:
                    going_rate = int(rate_rows.iloc[0][going_rate_col])
                except (TypeError, ValueError):
                    going_rate = None
            if new_entrant_col is not None:
                try:
                    new_entrant_rate = int(rate_rows.iloc[0][new_entrant_col])
                except (TypeError, ValueError):
                    new_entrant_rate = None

    offered = _offered_salary(jd)
    ne_eligible = _new_entrant_eligible(user)

    threshold: Optional[int] = None
    if ne_eligible and new_entrant_rate is not None:
        threshold = new_entrant_rate
    elif going_rate is not None:
        threshold = going_rate

    below = False
    shortfall: Optional[int] = None
    if offered is not None and threshold is not None:
        if offered < threshold:
            below = True
            shortfall = threshold - offered

    return SocCheckResult(
        soc_code=soc_code,
        soc_title=soc_title,
        on_appendix_skilled_occupations=on_appendix,
        going_rate_gbp=going_rate,
        new_entrant_rate_gbp=new_entrant_rate,
        offered_salary_gbp=offered,
        below_threshold=below,
        shortfall_gbp=shortfall,
        new_entrant_eligible=ne_eligible,
    )
