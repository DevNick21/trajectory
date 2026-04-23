"""Phase 4 — Cover Letter Writer.

Produces a culture-cited cover letter in the user's voice.
System prompt verbatim from AGENTS.md §13.
"""

from __future__ import annotations

from ..prompts import load_prompt

import json
from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import (
    CareerEntry,
    CoverLetterOutput,
    ExtractedJobDescription,
    ResearchBundle,
    STARPolish,
    UserProfile,
    WritingStyleProfile,
)
from ..validators.banned_phrases import contains_banned
from ..validators.citations import ValidationContext, validate_output

SYSTEM_PROMPT = load_prompt("cover_letter")


def _make_post_validate(citation_ctx: Optional[ValidationContext]):
    def _post_validate(cl: CoverLetterOutput) -> list[str]:
        failures: list[str] = []
        all_text = " ".join(cl.paragraphs)
        for phrase in contains_banned(all_text):
            failures.append(f"Banned phrase in cover letter: '{phrase}'")
        if cl.word_count < 250 or cl.word_count > 380:
            failures.append(
                f"Cover letter word count {cl.word_count} outside 250-380 range"
            )
        if citation_ctx is not None:
            failures.extend(validate_output(cl, citation_ctx))
        return failures

    return _post_validate


async def generate(
    jd: ExtractedJobDescription,
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
    style_profile: WritingStyleProfile,
    star_material: Optional[list[STARPolish]] = None,
    citation_ctx: Optional[ValidationContext] = None,
) -> CoverLetterOutput:
    company = research_bundle.company_research

    style_hint = (
        f"tone={style_profile.tone}, "
        f"formality={style_profile.formality_level}/10, "
        f"hedging={style_profile.hedging_tendency}"
    )
    if style_profile.sample_count < 3:
        style_hint += " (low confidence — directional only)"

    hiring_manager = (
        jd.hiring_manager_name if jd.hiring_manager_named and jd.hiring_manager_name
        else "Hiring Team"
    )

    polishes_summary = []
    if star_material:
        for p in star_material:
            polishes_summary.append(
                {
                    "question": p.question,
                    "action": p.action.text,
                    "result": p.result.text,
                }
            )

    entries_summary = [
        {"entry_id": e.entry_id, "kind": e.kind, "text": e.raw_text[:400]}
        for e in retrieved_entries[:10]
    ]

    culture_with_sources = [
        {"claim": c.claim, "url": c.url, "snippet": c.verbatim_snippet}
        for c in company.culture_claims[:6]
    ]

    user_input = json.dumps(
        {
            "role": jd.role_title,
            "company": company.company_name,
            "addressing_to": hiring_manager,
            "jd_required_skills": jd.required_skills[:8],
            "jd_specificity_signals": jd.specificity_signals[:5],
            "culture_claims": culture_with_sources,
            "recent_activity": company.recent_activity_signals[:3],
            "user_name": user.name,
            "user_motivations": user.motivations[:5],
            "writing_style": {
                "hint": style_hint,
                "signature_patterns": style_profile.signature_patterns[:5],
                "avoided_patterns": style_profile.avoided_patterns[:5],
                "examples": style_profile.examples[:3],
            },
            "career_entries": entries_summary,
            "star_polishes": polishes_summary,
        },
        default=str,
    )

    return await call_agent(
        agent_name="cover_letter",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=CoverLetterOutput,
        model=settings.opus_model_id,
        effort="xhigh",
        post_validate=_make_post_validate(citation_ctx),
    )
