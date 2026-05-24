"""Interview questions — design + predict in one module.

Replaces the previously-separate `question_designer.py` (Phase 3,
3 questions for the user to think about) and `likely_questions.py`
(Phase 4, 8-12 questions the user should expect to be asked).

The two used to live in separate files with mostly-duplicated user-
input construction and identical retrieval patterns. They share this
module now:
  - `_build_user_input()` builds the shared role + company + career
    entries digest once.
  - `design()` calls Haiku with the question-designer system prompt
    and the QuestionSet output schema.
  - `predict()` calls Haiku with the likely-questions prompt and the
    LikelyQuestionsOutput schema (carries citations).

Both prompts live as separate markdown files in `prompts/`, loaded
on import. Both flows use Haiku (downgraded from Sonnet 2026-05-22 —
question generation is pattern-matching against a known JD + culture
context, not deep judgement).
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from ..config import settings
from ..llm import call_agent
from ..prompts import load_prompt
from ..schemas import (
    CareerEntry,
    ExtractedJobDescription,
    LikelyQuestionsOutput,
    QuestionSet,
    ResearchBundle,
    UserProfile,
    Verdict,
)
from ..validators.banned_phrases import contains_banned
from ..validators.citations import ValidationContext, validate_output


_DESIGNER_SYSTEM_PROMPT = load_prompt("question_designer")
_PREDICTOR_SYSTEM_PROMPT = load_prompt("likely_questions")


# ---------------------------------------------------------------------------
# Shared user-input builder
# ---------------------------------------------------------------------------


def _build_user_input(
    *,
    jd: ExtractedJobDescription,
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
    verdict: Optional[Verdict] = None,
    entries_text_limit: int = 400,
    entries_count_limit: int = 10,
) -> str:
    """Construct the JSON user input both flows share.

    Includes career-entries (sliced + length-capped), JD signals,
    company culture claims, user motivations. Verdict stretch concerns
    are added when supplied (the designer cares; the predictor doesn't).
    """
    company = research_bundle.company_research
    entries_summary = [
        {
            "entry_id": e.entry_id,
            "kind": e.kind,
            "text": e.raw_text[:entries_text_limit],
        }
        for e in retrieved_entries[:entries_count_limit]
    ]
    payload: dict = {
        "role": jd.role_title,
        "seniority": jd.seniority_signal,
        "company": company.company_name,
        "jd_required_skills": jd.required_skills,
        "jd_specificity_signals": jd.specificity_signals[:5],
        "jd_vagueness_signals": jd.vagueness_signals[:3],
        "culture_claims": [
            {
                "claim": c.claim,
                "url": c.url,
                "snippet": c.verbatim_snippet[:100],
            }
            for c in company.culture_claims[:5]
        ],
        "tech_stack_signals": company.tech_stack_signals[:5],
        "user_motivations": user.motivations[:5],
        "career_entries": entries_summary,
    }
    if verdict is not None:
        payload["verdict_stretch_concerns"] = [
            c.type for c in verdict.stretch_concerns
        ]
    return json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# Mode 1 — design 3 questions for the user to think about (Phase 3)
# ---------------------------------------------------------------------------


_BANNED_OPENERS = re.compile(
    r"^(tell me about a time|describe a situation where|"
    r"walk me through|give an example of)",
    re.IGNORECASE,
)


def _validate_design(qs: QuestionSet) -> list[str]:
    failures: list[str] = []
    if len(qs.questions) != 3:
        failures.append(f"Expected exactly 3 questions, got {len(qs.questions)}")
    for i, q in enumerate(qs.questions):
        if _BANNED_OPENERS.match(q.question_text.strip()):
            failures.append(
                f"Question {i+1} uses a banned opener: {q.question_text[:60]}"
            )
    return failures


async def design(
    *,
    verdict: Verdict,
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
    session_id: Optional[str] = None,
) -> QuestionSet:
    """Generate 3 role-specific questions after a GO verdict."""
    user_input = _build_user_input(
        jd=research_bundle.extracted_jd,
        research_bundle=research_bundle,
        user=user,
        retrieved_entries=retrieved_entries,
        verdict=verdict,
        entries_text_limit=400,
        entries_count_limit=8,
    )
    return await call_agent(
        agent_name="interview_questions.design",
        system_prompt=_DESIGNER_SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=QuestionSet,
        model=settings.haiku_model_id,
        effort="medium",
        session_id=session_id,
        post_validate=_validate_design,
    )


# ---------------------------------------------------------------------------
# Mode 2 — predict 8-12 interview questions (Phase 4)
# ---------------------------------------------------------------------------


def _make_predict_validator(citation_ctx: Optional[ValidationContext]) -> Any:
    def _validate(lq: LikelyQuestionsOutput) -> list[str]:
        failures: list[str] = []
        if not (8 <= len(lq.questions) <= 12):
            failures.append(
                f"Expected 8-12 questions, got {len(lq.questions)}"
            )
        for q in lq.questions:
            for phrase in contains_banned(q.strategy_note):
                failures.append(f"Banned phrase in strategy_note: '{phrase}'")
            for phrase in contains_banned(q.question):
                failures.append(f"Banned phrase in question text: '{phrase}'")
        if citation_ctx is not None:
            failures.extend(validate_output(lq, citation_ctx))
        return failures

    return _validate


async def predict(
    *,
    jd: ExtractedJobDescription,
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
    citation_ctx: Optional[ValidationContext] = None,
) -> LikelyQuestionsOutput:
    """Predict 8-12 interview questions the user should expect."""
    user_input = _build_user_input(
        jd=jd,
        research_bundle=research_bundle,
        user=user,
        retrieved_entries=retrieved_entries,
        entries_text_limit=300,
        entries_count_limit=10,
    )
    return await call_agent(
        agent_name="interview_questions.predict",
        system_prompt=_PREDICTOR_SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=LikelyQuestionsOutput,
        model=settings.haiku_model_id,
        effort="medium",
        post_validate=_make_predict_validator(citation_ctx),
    )
