"""Managed salary strategist (PROCESS Entry 45).

Live-market-equipped salary recommendation. Pulls real posted-band
data from sites that DO show salaries (Wellfound, Otta, Hacker News
"Who's Hiring", company careers pages with explicit ranges) — bypassing
the LinkedIn/Indeed degradation in `salary_data.fetch`. Code Execution
runs the percentile / Monte Carlo math instead of having Opus reason
numerically in prose.

Triggered when `settings.enable_managed_salary_strategist=True`.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..config import settings
from ..llm import call_with_tools
from ..prompts import load_prompt
from ..schemas import (
    JobSearchContext,
    ResearchBundle,
    SalaryRecommendation,
    UserProfile,
    WritingStyleProfile,
)
from ..server_tools import CODE_EXECUTION, WEB_FETCH, WEB_SEARCH
from . import _register_session

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT_BASE = load_prompt("salary_strategist")
_LIVE_ADDENDUM = """

## Managed live-research mode (enable_managed_salary_strategist=True)

You have Web Search, Web Fetch, AND Code Execution tools. Use them.

Before recommending, do up to 2 targeted lookups for actual UK posted
bands at this seniority:
  - Wellfound / Otta / Hacker News "Who's Hiring" for the role title
    + level, UK-located
  - The company's own careers page (might have an explicit range)

Hard cap: 2 fetches, then move on. ASHE in the bundle is the floor;
fetched data is top-up signal.

For percentile math (where does the user's target sit vs ASHE +
collected market data?), USE the Code Execution tool — write actual
Python, not prose-based reasoning. A small Monte Carlo over the
collected band + the user's recent_rejections / months_until_visa_expiry
is the right shape for `urgency_note`.

Citations: each `reasoning_point` cites either the gov_data field
(ASHE p10/p50/p90, SOC going rate) or the fetched job-posting URL +
verbatim_snippet of the salary line. The recommendation must surface
ANY conflict between ASHE and live posted bands as a `data_gap`
entry, not silently average.
"""

SYSTEM_PROMPT = _SYSTEM_PROMPT_BASE + _LIVE_ADDENDUM


async def run(
    *,
    jd,
    research_bundle: ResearchBundle,
    user: UserProfile,
    context: JobSearchContext,
    style_profile: WritingStyleProfile,
    session_id: Optional[str] = None,
) -> SalaryRecommendation:
    """Live-market-equipped salary recommendation."""

    sal = research_bundle.salary_signals
    soc = research_bundle.soc_check

    user_input = json.dumps({
        "role": jd.role_title,
        "location": jd.location,
        "posted_salary_band": jd.salary_band,
        "user_floor": user.salary_floor,
        "user_target": user.salary_target,
        "user_type": user.user_type,
        "urgency": context.urgency_level,
        "recent_rejections": context.recent_rejections_count,
        "months_until_visa_expiry": context.months_until_visa_expiry,
        "search_duration_months": context.search_duration_months,
        "ashe": (
            sal.ashe.model_dump(mode="json") if sal and sal.ashe else None
        ),
        "soc_check": (
            soc.model_dump(mode="json") if soc else None
        ),
        "writing_style": {
            "tone": style_profile.tone,
            "formality_level": style_profile.formality_level,
            "hedging_tendency": style_profile.hedging_tendency,
            "examples": style_profile.examples[:3],
        },
        "instruction": (
            "Use Web Search + Web Fetch for real UK posted bands at this "
            "seniority, then Code Execution for the percentile-position "
            "math. Output a SalaryRecommendation with cited reasoning."
        ),
    }, default=str)

    def _pv(out: SalaryRecommendation) -> list[str]:
        problems: list[str] = []
        if not out.reasoning:
            problems.append("reasoning empty; need 3-5 ReasoningPoint entries.")
        no_cite = [
            i for i, rp in enumerate(out.reasoning)
            if not getattr(rp, "citation", None)
        ]
        if no_cite:
            problems.append(
                f"reasoning[{no_cite[:3]}] missing citation. "
                "Each ReasoningPoint needs a Citation."
            )
        if out.opening_number <= 0:
            problems.append("opening_number must be > 0.")
        if out.floor > out.ceiling:
            problems.append(f"floor {out.floor} > ceiling {out.ceiling}.")
        return problems

    rec = await call_with_tools(
        agent_name="salary_strategist_managed",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=SalaryRecommendation,
        server_tools=[WEB_SEARCH, WEB_FETCH, CODE_EXECUTION],
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
        post_validate=_pv,
    )

    logger.info(
        "salary_strategist_managed: opening=%d floor=%d ceiling=%d "
        "confidence=%s data_gaps=%d",
        rec.opening_number, rec.floor, rec.ceiling, rec.confidence,
        len(rec.data_gaps),
    )
    return rec


_register_session("salary_strategist_managed", run)
