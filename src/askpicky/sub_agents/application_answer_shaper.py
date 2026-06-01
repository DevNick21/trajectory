"""Application assist — answer shaper.

Turns a user's rough draft/transcript plus approved memory suggestions into a
submission-ready answer. This is a high-stakes user-facing generator, so it
uses the normal tier and receives full writing-style context.

System prompt: src/askpicky/prompts/application_answer_shaper.md
"""

from __future__ import annotations

import json
from typing import Optional

from ..llm import call_agent
from ..prompts import load_prompt
from ..schemas import (
    AdviceSnippet,
    ApplicationAnswerOutput,
    MemorySuggestion,
    QuestionPattern,
    UserProfile,
    WritingStyleProfile,
)
from ..validators.banned_phrases import contains_banned
from ..validators.content_shield import ContentIntegrityRejected, shield

SYSTEM_PROMPT = load_prompt("application_answer_shaper")


def _word_count(text: str) -> int:
    return len(text.split())


def _post_validate(output: ApplicationAnswerOutput) -> list[str]:
    failures: list[str] = []
    for phrase in contains_banned(output.final_answer):
        failures.append(f"Banned phrase in final answer: {phrase!r}")
    actual_words = _word_count(output.final_answer)
    if abs(output.word_count - actual_words) > 3:
        failures.append("word_count must be within 3 words of final_answer token count.")
    return failures


async def shape(
    *,
    question_text: str,
    raw_draft: str,
    user: UserProfile,
    style_profile: WritingStyleProfile,
    question_pattern: QuestionPattern,
    memory_suggestions: list[MemorySuggestion],
    advice_snippets: list[AdviceSnippet],
    word_limit: Optional[int] = None,
    transcript: Optional[str] = None,
    job_context: Optional[dict] = None,
    private_content: bool = False,
    session_id: Optional[str] = None,
) -> ApplicationAnswerOutput:
    """Generate the final polished answer.

    Model: normal tier (DeepSeek V4 Pro by default). Why: this is a
    user-facing generator where voice preservation and fact discipline matter,
    but it receives already-selected memory and a tight schema, so the strong
    verdict tier is unnecessary.
    """

    q_shield = await shield(
        question_text,
        source_type="application_question",
        downstream_agent="application_answer_shaper",
    )
    draft_shield = await shield(
        raw_draft,
        source_type="application_answer",
        downstream_agent="application_answer_shaper",
    )
    transcript_clean = None
    shield_results = [q_shield, draft_shield]
    if transcript:
        transcript_shield = await shield(
            transcript,
            source_type="application_answer",
            downstream_agent="application_answer_shaper",
        )
        transcript_clean = transcript_shield.cleaned_text
        shield_results.append(transcript_shield)

    for res in shield_results:
        if res.verdict and res.verdict.recommended_action == "REJECT":
            raise ContentIntegrityRejected(res.verdict, "application_assist")

    style_payload = {
        "tone": style_profile.tone,
        "sentence_length_pref": style_profile.sentence_length_pref,
        "formality_level": style_profile.formality_level,
        "hedging_tendency": style_profile.hedging_tendency,
        "signature_patterns": style_profile.signature_patterns[:6],
        "avoided_patterns": style_profile.avoided_patterns[:8],
        "examples": style_profile.examples[:4],
        "sample_count": style_profile.sample_count,
        "low_confidence_reason": style_profile.low_confidence_reason,
    }

    user_input = json.dumps(
        {
            "question_text": q_shield.cleaned_text,
            "question_pattern": question_pattern.model_dump(mode="json"),
            "word_limit": word_limit,
            "raw_draft": draft_shield.cleaned_text,
            "transcript": transcript_clean,
            "memory_suggestions": [
                m.model_dump(mode="json") for m in memory_suggestions[:8]
            ],
            "advice_snippets": [
                a.model_dump(mode="json") for a in advice_snippets[:5]
            ],
            "writing_style_profile": style_payload,
            "job_context": job_context or {},
            "private_content": private_content,
        },
        default=str,
    )

    return await call_agent(
        agent_name="application_answer_shaper",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=ApplicationAnswerOutput,
        effort="high",
        session_id=session_id,
        post_validate=_post_validate,
        max_tokens=2_048,
    )
