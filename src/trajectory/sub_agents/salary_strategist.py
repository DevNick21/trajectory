"""Phase 4 — Salary Strategist.

Produces opening number, floor, ceiling, and scripts.
System prompt verbatim from AGENTS.md §11.
"""

from __future__ import annotations

from ..prompts import load_prompt

import json
from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import (
    JobSearchContext,
    ExtractedJobDescription,
    ResearchBundle,
    SalaryRecommendation,
    UserProfile,
    WritingStyleProfile,
)
from ..validators.banned_phrases import contains_banned
from ..validators.citations import ValidationContext, validate_output

SYSTEM_PROMPT = load_prompt("salary_strategist")


def _make_post_validate(citation_ctx: Optional[ValidationContext]):
    def _post_validate(rec: SalaryRecommendation) -> list[str]:
        failures: list[str] = []
        if not (rec.floor <= rec.opening_number <= rec.ceiling):
            failures.append(
                f"opening_number {rec.opening_number} not in [{rec.floor}, {rec.ceiling}]"
            )
        all_scripts = " ".join(rec.scripts.values())
        for phrase in contains_banned(all_scripts):
            failures.append(f"Banned phrase in salary script: '{phrase}'")
        if citation_ctx is not None:
            failures.extend(validate_output(rec, citation_ctx))
        return failures

    return _post_validate


async def generate(
    jd: ExtractedJobDescription,
    research_bundle: ResearchBundle,
    user: UserProfile,
    context: JobSearchContext,
    style_profile: WritingStyleProfile,
    citation_ctx: Optional[ValidationContext] = None,
) -> SalaryRecommendation:
    style_hint = (
        f"tone={style_profile.tone}, "
        f"formality={style_profile.formality_level}/10, "
        f"hedging={style_profile.hedging_tendency}"
    )

    ch_summary: dict = {}
    if research_bundle.companies_house:
        ch = research_bundle.companies_house
        ch_summary = {
            "status": ch.status,
            "accounts_overdue": ch.accounts_overdue,
            "no_filings_in_years": ch.no_filings_in_years,
        }

    soc_summary: dict = {}
    if research_bundle.soc_check:
        soc = research_bundle.soc_check
        soc_summary = {
            "going_rate_gbp": soc.going_rate_gbp,
            "new_entrant_rate_gbp": soc.new_entrant_rate_gbp,
            "below_threshold": soc.below_threshold,
            "shortfall_gbp": soc.shortfall_gbp,
        }

    # Rule 3: writing style must flow into every generator — salary scripts
    # are voice-sensitive, so pass the full style fingerprint, not just a
    # short hint string.
    sal = research_bundle.salary_signals
    ashe_summary: dict = {}
    if sal.ashe:
        ashe_summary = {
            "granularity": sal.ashe.granularity,
            "p10": sal.ashe.p10,
            "p50": sal.ashe.p50,
            "p90": sal.ashe.p90,
            "sample_year": sal.ashe.sample_year,
        }

    # Cross-application memory recall (PROCESS Entry 43, Workstream E):
    # surface what this user has historically asked vs accepted at past
    # negotiations so the strategist can calibrate its opening number.
    # Best-effort — empty list when no memory yet.
    try:
        from ..memory import recall
        prior_negotiations = await recall(
            user_id=user.user_id,
            kind="negotiation_result",
            limit=5,
        )
        prior_offers = await recall(
            user_id=user.user_id,
            kind="application_outcome",
            limit=5,
        )
    except Exception:
        prior_negotiations = []
        prior_offers = []

    user_input = json.dumps(
        {
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
            "salary_signals": {
                "ashe": ashe_summary,
                "posted_band": sal.posted_band.model_dump() if sal.posted_band else None,
                "aggregated_postings": sal.aggregated_postings.model_dump() if sal.aggregated_postings else None,
                "sources_consulted": sal.sources_consulted,
            },
            "companies_house": ch_summary,
            "soc_check": soc_summary,
            "writing_style": {
                "hint": style_hint,
                "signature_patterns": style_profile.signature_patterns[:5],
                "avoided_patterns": style_profile.avoided_patterns[:5],
                "examples": style_profile.examples[:3],
            },
            "cross_app_memory": {
                "prior_negotiations": prior_negotiations,
                "prior_offers": prior_offers,
            },
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
        post_validate=_make_post_validate(citation_ctx),
    )
