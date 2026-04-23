"""Phase 3 — STAR Polisher.

Restructures a raw user answer into STAR format without inventing facts.
System prompt verbatim from AGENTS.md §8.
"""

from __future__ import annotations

from ..prompts import load_prompt

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

SYSTEM_PROMPT = load_prompt("star_polisher")


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
