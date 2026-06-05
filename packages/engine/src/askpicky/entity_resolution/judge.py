"""LLM-as-judge fallback for ambiguous resolver candidates.

The deterministic layers (alias expansion, footer regex, shell penalty,
multi-token blocking) cover the common case. But there are situations
they can't reach:

  - The footer didn't contain the boilerplate (or the scraper missed
    the page where it lives).
  - Multiple CH candidates score above threshold and the differences
    are signal-poor (e.g. two active companies with similar names).
  - The top candidate has weak signals (just incorporated, no
    filings, dormant) but isn't an obvious shell to drop outright.

In those cases this module asks the fast tier model (DeepSeek V4 Flash)
to look at the candidate set + whatever context we have (raw input, domain,
scraped page hints) and pick the most plausible trading entity — or refuse
if none look right.

Runs only on ~5-10% of resolutions (the genuinely ambiguous ones),
so the latency + cost overhead is bounded. This is a pattern-matching task,
not judgement-heavy, so the fast tier is fine.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from ..config import settings
from ..llm import call_agent

logger = logging.getLogger(__name__)


# When the top candidate's confidence is below this, OR when the top
# two are within this score-gap of each other, fire the judge.
LOW_CONFIDENCE_THRESHOLD = 92.0
AMBIGUOUS_GAP_THRESHOLD = 4.0


_SYSTEM_PROMPT = """You are an entity-resolution judge. Given a
raw company name (often the brand from a job posting), an optional
domain hint, and a list of candidate UK Companies House entries,
return the company_number (CRN) of the actual trading entity the
job posting is for — or 'none' if no candidate looks right.

Rules:
1. The trading entity is the one paying salaries and signing
   employment contracts. NOT a holding company, not a shell, not a
   dissolved entity unless the role pre-dates dissolution.
2. Brand names often differ from legal names. "loveholidays" is the
   brand; "WE LOVE HOLIDAYS LIMITED" is the legal name. Pick the
   legal name that matches the brand semantically + has trading
   history (active status, multi-year incorporation, filings).
3. Reject obvious shells: dissolved < 1 year after incorporation,
   active but no filings ever, or recent incorporations with no
   public footprint at the scale the brand implies.
4. If two candidates are equally plausible, prefer the older one
   with more filings. Trading scale shows up in CH filing history.
5. If none are plausible (e.g. the JD is from a US company that
   only has a small UK subsidiary in the candidate list and the
   subsidiary doesn't match), return crn='none' and explain.

Output: { "crn": "12345678" or "none", "reasoning": "<one sentence>" }"""


class JudgeCandidate(BaseModel):
    """One CH candidate for the judge to consider."""

    company_number: str
    company_name: str
    company_status: Optional[str] = None
    date_of_creation: Optional[str] = None
    ensemble_score: Optional[float] = None
    incorporation_age_days: Optional[int] = None


class JudgeVerdict(BaseModel):
    crn: str = Field(description="The chosen CRN, or 'none' if no candidate matches.")
    reasoning: str = Field(min_length=10, max_length=400)


def should_invoke_judge(
    *,
    top_score: float,
    second_score: Optional[float],
    top_hit: dict,
) -> bool:
    """Heuristic: when should we spend the LLM call?

    - Top score below LOW_CONFIDENCE_THRESHOLD: yes
    - Top two scores within AMBIGUOUS_GAP_THRESHOLD: yes (tie-break)
    - Top hit looks weak (no filings / very new): yes (sanity-check)
    - Otherwise: no, ship the deterministic pick
    """
    if top_score < LOW_CONFIDENCE_THRESHOLD:
        return True
    if second_score is not None and (top_score - second_score) < AMBIGUOUS_GAP_THRESHOLD:
        return True
    # Suspicious-signals check (lighter than the shell-candidate veto).
    status = (top_hit.get("company_status") or "").lower()
    date_of_creation = top_hit.get("date_of_creation") or top_hit.get("incorporation_date")
    if status in {"dissolved", "liquidation"}:
        return True
    if date_of_creation:
        try:
            from datetime import date as _date, datetime as _dt
            age_days = (_date.today() - _dt.strptime(date_of_creation, "%Y-%m-%d").date()).days
            if age_days < 730:  # under 2 years — sanity check
                return True
        except (ValueError, TypeError):
            pass
    return False


async def judge_candidates(
    *,
    raw_name: str,
    domain: Optional[str],
    candidates: list[JudgeCandidate],
    page_context: Optional[str] = None,
) -> Optional[str]:
    """Return the CRN the judge picks, or None on 'none' / failure.

    The page_context is optional — when supplied (e.g. the first
    500 chars of the scraped /about page) it gives the judge
    semantic context. Without it the judge runs name-only.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        # Nothing to disambiguate — return the only candidate's CRN.
        return candidates[0].company_number

    user_input_lines: list[str] = [
        f"raw_name: {raw_name}",
        f"domain: {domain or '(none)'}",
    ]
    if page_context:
        snippet = page_context[:600].replace("\n", " ").strip()
        user_input_lines.append(f"page_context: {snippet}")
    user_input_lines.append("candidates:")
    for c in candidates:
        user_input_lines.append(
            f"  - crn={c.company_number} name={c.company_name!r} "
            f"status={c.company_status or '?'} "
            f"incorporated={c.date_of_creation or '?'} "
            f"age_days={c.incorporation_age_days if c.incorporation_age_days is not None else '?'} "
            f"score={c.ensemble_score if c.ensemble_score is not None else '?'}"
        )
    user_input = "\n".join(user_input_lines)

    try:
        verdict: JudgeVerdict = await call_agent(
            agent_name="entity_judge",
            system_prompt=_SYSTEM_PROMPT,
            user_input=user_input,
            output_schema=JudgeVerdict,
            effort="medium",
        )
    except Exception as exc:
        logger.warning("entity_judge call failed: %s", exc)
        return None

    logger.info(
        "entity_judge picked crn=%s — %s",
        verdict.crn, verdict.reasoning,
    )
    if verdict.crn.lower() == "none":
        return None
    # Sanity: the judge should pick one of the offered candidates.
    valid_crns = {c.company_number for c in candidates}
    if verdict.crn not in valid_crns:
        logger.warning(
            "entity_judge returned crn=%s not in candidate set %s; ignoring",
            verdict.crn, valid_crns,
        )
        return None
    return verdict.crn
