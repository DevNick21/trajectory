"""Phase 4 — Likely Questions Predictor.

Predicts 8-12 interview questions for a specific role.
System prompt verbatim from AGENTS.md §14.
"""

from __future__ import annotations

from ..prompts import load_prompt

import json
from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import (
    CareerEntry,
    ExtractedJobDescription,
    LikelyQuestionsOutput,
    ResearchBundle,
    UserProfile,
)
from ..validators.banned_phrases import contains_banned
from ..validators.citations import ValidationContext, validate_output

SYSTEM_PROMPT = load_prompt("likely_questions")


def _make_post_validate(citation_ctx: Optional[ValidationContext]):
    def _post_validate(lq: LikelyQuestionsOutput) -> list[str]:
        failures: list[str] = []
        if not (8 <= len(lq.questions) <= 12):
            failures.append(
                f"Expected 8-12 questions, got {len(lq.questions)}"
            )
        for q in lq.questions:
            for phrase in contains_banned(q.strategy_note):
                failures.append(f"Banned phrase in strategy_note: '{phrase}'")
            # Banned phrases in the question text itself matter too — the
            # user pastes this into prep and cliché phrasing wastes space.
            for phrase in contains_banned(q.question):
                failures.append(f"Banned phrase in question text: '{phrase}'")
        if citation_ctx is not None:
            failures.extend(validate_output(lq, citation_ctx))
        return failures

    return _post_validate


async def generate(
    jd: ExtractedJobDescription,
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
    citation_ctx: Optional[ValidationContext] = None,
) -> LikelyQuestionsOutput:
    company = research_bundle.company_research

    entries_summary = [
        {"entry_id": e.entry_id, "kind": e.kind, "text": e.raw_text[:300]}
        for e in retrieved_entries[:10]
    ]

    user_input = json.dumps(
        {
            "role": jd.role_title,
            "seniority": jd.seniority_signal,
            "company": company.company_name,
            "jd_required_skills": jd.required_skills,
            "jd_specificity_signals": jd.specificity_signals[:5],
            "jd_vagueness_signals": jd.vagueness_signals[:3],
            "culture_claims": [
                {"claim": c.claim, "url": c.url, "snippet": c.verbatim_snippet[:100]}
                for c in company.culture_claims[:5]
            ],
            "tech_stack_signals": company.tech_stack_signals[:5],
            "user_motivations": user.motivations[:5],
            "career_entries": entries_summary,
        },
        default=str,
    )

    return await call_agent(
        agent_name="likely_questions",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=LikelyQuestionsOutput,
        model=settings.opus_model_id,
        effort="xhigh",
        post_validate=_make_post_validate(citation_ctx),
    )
