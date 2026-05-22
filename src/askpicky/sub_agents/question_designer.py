"""Phase 3 — Question Designer.

Generates exactly 3 role-specific questions after a GO verdict.
System prompt verbatim from AGENTS.md §7.
"""

from __future__ import annotations

from ..prompts import load_prompt

import json
import re
from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import (
    CareerEntry,
    QuestionSet,
    ResearchBundle,
    UserProfile,
    Verdict,
)

SYSTEM_PROMPT = load_prompt("question_designer")

_BANNED_OPENERS = re.compile(
    r"^(tell me about a time|describe a situation where|walk me through|give an example of)",
    re.IGNORECASE,
)


def _post_validate(qs: QuestionSet) -> list[str]:
    failures = []
    if len(qs.questions) != 3:
        failures.append(f"Expected exactly 3 questions, got {len(qs.questions)}")
    for i, q in enumerate(qs.questions):
        if _BANNED_OPENERS.match(q.question_text.strip()):
            failures.append(f"Question {i+1} uses a banned opener: {q.question_text[:60]}")
    return failures


async def generate(
    verdict: Verdict,
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
    session_id: Optional[str] = None,
) -> QuestionSet:
    jd = research_bundle.extracted_jd
    concerns = [c.type for c in verdict.stretch_concerns]
    entries_summary = [
        {"entry_id": e.entry_id, "kind": e.kind, "text": e.raw_text[:400]}
        for e in retrieved_entries[:8]
    ]

    user_input = json.dumps(
        {
            "role": jd.role_title,
            "company": research_bundle.company_research.company_name,
            "jd_required_skills": jd.required_skills,
            "jd_specificity_signals": jd.specificity_signals[:5],
            "verdict_stretch_concerns": concerns,
            "culture_claims": [
                c.claim for c in research_bundle.company_research.culture_claims[:5]
            ],
            "user_motivations": user.motivations,
            "career_entries": entries_summary,
        },
        default=str,
    )

    return await call_agent(
        agent_name="question_designer",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=QuestionSet,
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
        post_validate=_post_validate,
    )
