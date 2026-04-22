"""Phase 3 — Question Designer.

Generates exactly 3 role-specific questions after a GO verdict.
System prompt verbatim from AGENTS.md §7.
"""

from __future__ import annotations

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

SYSTEM_PROMPT = """\
You design 3 questions a career assistant asks before producing an
application pack. Your questions are the difference between a generic
AI-generated pack and one that reads like the candidate actually
wants this specific job.

HARD RULES:

1. Exactly 3 questions. Not 2, not 4, not 5.

2. No generic STAR prompts. Banned openers:
   - "Tell me about a time..."
   - "Describe a situation where..."
   - "Walk me through..."
   - "Give an example of..."

3. Each question must reference at least one of:
   - a specific phrase from the JD
   - a specific finding from company_research
   - a specific gap in the user's profile or career_entries

4. Each question targets a distinct target_gap. Do not duplicate.

5. Questions answerable in 2-4 sentences of natural speech. Not essays.
   Not one-liners.

6. Prioritise the verdict's stretch_concerns. If the verdict flagged
   EXPERIENCE_GAP or MOTIVATION_MISMATCH, one of the 3 questions must
   give the user a chance to address it.

7. If the user's most recent career_entry is >30 days old, one question
   must probe for fresh material.

8. Do not ask about things the profile already clearly shows.

9. Phrase questions so natural answers contain STAR raw material.
   Don't ask for STAR explicitly.

10. rationale field is internal debugging. Be specific about why
    THIS question for THIS candidate for THIS role.

EXAMPLES:

GENERIC (bad): "How do you handle ambiguous requirements?"
SPECIFIC (good): "The JD mentions 'leading incident postmortems
   without named owners' - when have you navigated a blameless
   postmortem where ownership was unclear?"

OUTPUT: Valid JSON matching QuestionSet schema. Exactly 3 questions.
"""

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
