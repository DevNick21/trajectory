"""Application assist — background memory extractor.

Extracts reviewable ExperienceAtom / StoryFrame drafts from approved answers.
The API stores these as Memory Inbox items; they do not influence future
suggestions until approved or explicitly included.

System prompt: src/askpicky/prompts/memory_extractor.md
"""

from __future__ import annotations

import json
from typing import Optional

from ..llm import call_agent
from ..prompts import load_prompt
from ..schemas import AnswerAttempt, MemoryExtractionOutput
from ..validators.content_shield import ContentIntegrityRejected, shield

SYSTEM_PROMPT = load_prompt("memory_extractor")


def _post_validate(output: MemoryExtractionOutput) -> list[str]:
    failures: list[str] = []
    for atom in output.experience_atoms:
        if len(atom.text.split()) > 40:
            failures.append("ExperienceAtomDraft.text should stay atomic, not paragraph-length.")
    for story in output.story_frames:
        if len(story.summary.split()) > 140:
            failures.append("StoryFrameDraft.summary should be compact enough for Memory Inbox review.")
    return failures


async def extract(
    *,
    attempt: AnswerAttempt,
    session_id: Optional[str] = None,
) -> MemoryExtractionOutput:
    """Run richer extraction from an approved answer.

    Model: fast tier (DeepSeek V4 Flash by default). Why: this is structured
    extraction from validated user text into a tight schema. It can improve
    memory quality, but the deterministic extractor already captured a safe
    fallback, so strong-tier reasoning would add cost without blocking UX.
    """

    untrusted = "\n\n".join(
        [
            attempt.question_text,
            attempt.raw_draft,
            attempt.transcript or "",
            attempt.final_answer or "",
        ]
    )
    shielded = await shield(
        untrusted,
        source_type="application_answer",
        downstream_agent="memory_extractor",
    )
    if shielded.verdict and shielded.verdict.recommended_action == "REJECT":
        raise ContentIntegrityRejected(shielded.verdict, "memory_extractor")

    user_input = json.dumps(
        {
            "attempt": {
                "attempt_id": attempt.attempt_id,
                "question_text": attempt.question_text,
                "question_type": attempt.question_type,
                "raw_draft": attempt.raw_draft,
                "transcript": attempt.transcript,
                "final_answer": attempt.final_answer,
                "selected_memory_ids": attempt.selected_memory_ids,
                "company_name": attempt.company_name,
                "role_title": attempt.role_title,
            },
            "shielded_text": shielded.cleaned_text,
        },
        default=str,
    )

    return await call_agent(
        agent_name="memory_extractor",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=MemoryExtractionOutput,
        effort="medium",
        session_id=session_id,
        post_validate=_post_validate,
        max_tokens=2_048,
    )

