"""Phase 3 — STAR Polisher.

Restructures a raw user answer into STAR format without inventing facts.
System prompt verbatim from AGENTS.md §8.
"""

from __future__ import annotations

import json
from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import (
    DesignedQuestion,
    ExtractedJobDescription,
    STARPolish,
    WritingStyleProfile,
)
from ..validators.banned_phrases import contains_banned

SYSTEM_PROMPT = """\
Restructure a user's raw answer into STAR format (Situation, Task,
Action, Result).

You receive: the question asked, the user's raw answer, the JD
context, the user's writing_style_profile.

HARD RULES:

1. NEVER invent facts. If the user's answer doesn't contain a specific
   number, outcome, team size, or result, do not make one up.

2. If the Result is missing or vague in the raw answer, do NOT
   fabricate one. Instead, return `clarifying_question` with a
   specific follow-up: "You didn't mention the outcome - what
   happened to the error rate / ship date / customer?"

3. If Situation or Task is missing, same pattern: return a specific
   clarifying_question.

4. Write in the user's voice per writing_style_profile. Use their
   signature_patterns where natural. Never use avoided_patterns.
   If sample_count < 3, use the profile directionally only.

5. Keep each STAR component to 1-3 sentences. The goal is tight, real,
   specific.

6. Tie the Action and Result back to the JD's requirements when a
   natural connection exists. Do not force connections.

7. Output includes both the polished STAR and a confidence score
   (0-1) for each component based on how much raw material the user
   provided.

OUTPUT: Valid JSON matching STARPolish schema.
"""


def _post_validate(polish: STARPolish) -> list[str]:
    failures: list[str] = []
    all_text = " ".join(
        [
            polish.situation.text,
            polish.task.text,
            polish.action.text,
            polish.result.text,
        ]
    )
    for phrase in contains_banned(all_text):
        failures.append(f"Banned phrase in STAR output: '{phrase}'")
    return failures


async def polish(
    question: DesignedQuestion,
    raw_answer: str,
    jd: ExtractedJobDescription,
    style_profile: WritingStyleProfile,
    session_id: Optional[str] = None,
) -> STARPolish:
    style_hint = (
        f"tone={style_profile.tone}, "
        f"formality={style_profile.formality_level}/10, "
        f"hedging={style_profile.hedging_tendency}"
    )
    if style_profile.sample_count < 3:
        style_hint += " (low confidence — use directionally only)"

    user_input = json.dumps(
        {
            "question": question.question_text,
            "raw_answer": raw_answer,
            "jd_role": jd.role_title,
            "jd_required_skills": jd.required_skills[:8],
            "writing_style": {
                "hint": style_hint,
                "signature_patterns": style_profile.signature_patterns[:5],
                "avoided_patterns": style_profile.avoided_patterns[:5],
                "examples": style_profile.examples[:3],
            },
        },
        default=str,
    )

    return await call_agent(
        agent_name="star_polisher",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=STARPolish,
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
        post_validate=_post_validate,
    )
