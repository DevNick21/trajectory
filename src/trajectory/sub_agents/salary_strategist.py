"""Phase 4 — Salary Strategist.

Produces opening number, floor, ceiling, and scripts.
System prompt verbatim from AGENTS.md §11.
"""

from __future__ import annotations

import json
from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import (
    ExtractedJobDescription,
    CompanyResearch,
    CompaniesHouseSnapshot,
    JobSearchContext,
    SalaryRecommendation,
    SalarySignals,
    SocCheckResult,
    UserProfile,
    WritingStyleProfile,
)
from ..validators.banned_phrases import contains_banned

SYSTEM_PROMPT = """\
You are a salary negotiation advisor for a UK candidate.

Your job: recommend an opening_number, a walk-away floor, a ceiling for
later rounds, and exact phrasings for the moments recruiters ask.

You receive:
- extracted_jd
- company_research (including Companies House financial health)
- salary_data (Glassdoor / Levels / posted band, with sources)
- soc_check (visa holders only; includes threshold)
- user_profile (salary_floor, salary_target)
- job_search_context (urgency, recent rejections, visa expiry,
  current employment, search duration)
- writing_style_profile (for scripts)

HARD RULES:

1. Every number cited to real data. No vibes numbers. Cite:
   Glassdoor/Levels row, SOC going rate, company's published band,
   or a combination.

2. Visa holder floor = max(sponsor_floor, user_profile.salary_floor).
   Never recommend below sponsor_floor. Set sponsor_constraint_active.

3. Confidence calibration:
   - LOW: only 1 data source
   - MEDIUM: 2 sources agree within 15%
   - HIGH: 3+ sources agree within 10%

4. Anchor to the company's financial health (Companies House).
   Struggling small company → lean low, negotiate equity/other.
   Healthy growing company → lean high, cash compensates.

5. URGENCY-ADJUSTED opening_number (as percentile of comparable data):
   - LOW urgency     → 70-80th percentile
   - MEDIUM urgency  → 60-70th percentile (default)
   - HIGH urgency    → 55-65th percentile (prioritise offer security)
   - CRITICAL urgency → 50-60th percentile + add urgency_note

6. URGENCY-ADJUSTED scripts:
   - LOW: assertive phrasings, "I'd be looking for X"
   - MEDIUM: collaborative phrasings, "around X, happy to discuss"
   - HIGH: flexible phrasings, "X is my target, though I'm open"
   - CRITICAL: stability-first, "I'm looking for a role where I can
     settle in long-term, and X would make that work"

7. The opening_number is NOT the top of the range. It's the number
   the user would be genuinely happy with on day one, because the
   opening anchors the negotiation.

8. Scripts keys: recruiter_first_call, hiring_manager_ask,
   offer_stage_counter, pushback_response.

9. Scripts use writing_style_profile: tone, formality, signature
   patterns. Avoid "compensation package", "commensurate with
   experience", "my expectations". Use the user's voice.

10. If data is genuinely insufficient (no salary sources available),
    return confidence=LOW with a script that asks the recruiter to
    share their band first.

11. If urgency is HIGH or CRITICAL, add `urgency_note` explaining why
    opening is lower than the user's market range, and invite them
    to request a re-run if their situation changes.

OUTPUT: Valid JSON matching SalaryRecommendation schema.
"""


def _post_validate(rec: SalaryRecommendation) -> list[str]:
    failures: list[str] = []
    if not (rec.floor <= rec.opening_number <= rec.ceiling):
        failures.append(
            f"opening_number {rec.opening_number} not in [{rec.floor}, {rec.ceiling}]"
        )
    all_scripts = " ".join(rec.scripts.values())
    for phrase in contains_banned(all_scripts):
        failures.append(f"Banned phrase in salary script: '{phrase}'")
    return failures


async def strategise(
    jd: ExtractedJobDescription,
    company_research: CompanyResearch,
    salary_signals: SalarySignals,
    user: UserProfile,
    job_search_context: JobSearchContext,
    style_profile: WritingStyleProfile,
    companies_house: Optional[CompaniesHouseSnapshot] = None,
    soc_check: Optional[SocCheckResult] = None,
    session_id: Optional[str] = None,
) -> SalaryRecommendation:
    style_hint = (
        f"tone={style_profile.tone}, "
        f"formality={style_profile.formality_level}/10, "
        f"hedging={style_profile.hedging_tendency}"
    )

    ch_summary: dict = {}
    if companies_house:
        ch_summary = {
            "status": companies_house.status,
            "accounts_overdue": companies_house.accounts_overdue,
            "no_filings_in_years": companies_house.no_filings_in_years,
        }

    soc_summary: dict = {}
    if soc_check:
        soc_summary = {
            "going_rate_gbp": soc_check.going_rate_gbp,
            "new_entrant_rate_gbp": soc_check.new_entrant_rate_gbp,
            "below_threshold": soc_check.below_threshold,
            "shortfall_gbp": soc_check.shortfall_gbp,
        }

    user_input = json.dumps(
        {
            "role": jd.role_title,
            "location": jd.location,
            "posted_salary_band": jd.salary_band,
            "user_floor": user.salary_floor,
            "user_target": user.salary_target,
            "user_type": user.user_type,
            "urgency": job_search_context.urgency_level,
            "recent_rejections": job_search_context.recent_rejections_count,
            "months_until_visa_expiry": job_search_context.months_until_visa_expiry,
            "search_duration_months": job_search_context.search_duration_months,
            "salary_signals": {
                "posted_band": salary_signals.posted_band,
                "glassdoor_range": salary_signals.glassdoor_range,
                "market_p10": salary_signals.market_p10,
                "market_p50": salary_signals.market_p50,
                "market_p90": salary_signals.market_p90,
                "sources_consulted": salary_signals.sources_consulted,
            },
            "companies_house": ch_summary,
            "soc_check": soc_summary,
            "writing_style": style_hint,
            "signature_patterns": style_profile.signature_patterns[:5],
        },
        default=str,
    )

    return await call_agent(
        agent_name="salary_strategist",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=SalaryRecommendation,
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
        post_validate=_post_validate,
    )
