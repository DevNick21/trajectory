"""Phase 4 — CV Tailor (legacy single-call path).

Produces a CV tailored to a specific role, grounded in career history.
System prompt verbatim from AGENTS.md §12.

This is the original "stuff everything into the prompt" implementation.
Renamed from `cv_tailor.py` on 2026-04-23 (PROCESS.md Entry 36) when
the agentic-retrieval refactor was added. Production traffic stays on
this path until the agentic path passes A/B validation.

Dispatcher: `sub_agents/cv_tailor.py::generate` selects between this
and `cv_tailor_agentic.py` based on
`settings.enable_agentic_cv_tailor`. Untouched code below the docstring.
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
    CVOutput,
    ExtractedJobDescription,
    ResearchBundle,
    STARPolish,
    UserProfile,
    WritingStyleProfile,
)
from ..validators.banned_phrases import contains_banned
from ..validators.citations import ValidationContext, validate_output

SYSTEM_PROMPT = load_prompt("cv_tailor")

_CE_MARKER = re.compile(r"\[ce:[^\]]+\]")


def _make_post_validate(citation_ctx: Optional[ValidationContext]):
    def _post_validate(cv: CVOutput) -> list[str]:
        failures: list[str] = []
        all_text_parts = [cv.professional_summary]
        for role in cv.experience:
            for b in role.bullets:
                all_text_parts.append(b.text)
        all_text = " ".join(all_text_parts)
        clean = _CE_MARKER.sub("", all_text)
        for phrase in contains_banned(clean):
            failures.append(f"Banned phrase in CV: '{phrase}'")
        if citation_ctx is not None:
            failures.extend(validate_output(cv, citation_ctx))
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
) -> CVOutput:
    style_hint = (
        f"tone={style_profile.tone}, "
        f"formality={style_profile.formality_level}/10, "
        f"hedging={style_profile.hedging_tendency}"
    )
    if style_profile.sample_count < 3:
        style_hint += " (low confidence — directional only)"

    polishes_summary = []
    if star_material:
        for p in star_material:
            polishes_summary.append(
                {
                    "question": p.question,
                    "situation": p.situation.text,
                    "task": p.task.text,
                    "action": p.action.text,
                    "result": p.result.text,
                }
            )

    entries_summary = [
        {"entry_id": e.entry_id, "kind": e.kind, "text": e.raw_text[:500]}
        for e in retrieved_entries[:12]
    ]

    user_input = json.dumps(
        {
            "role": jd.role_title,
            "company": research_bundle.company_research.company_name,
            "jd_required_skills": jd.required_skills,
            "jd_specificity_signals": jd.specificity_signals[:5],
            "user_name": user.name,
            "user_location": user.base_location,
            "user_linkedin": user.linkedin_url,
            "user_github": user.github_url,
            "writing_style": {
                "hint": style_hint,
                "signature_patterns": style_profile.signature_patterns[:5],
                "avoided_patterns": style_profile.avoided_patterns[:5],
                "examples": style_profile.examples[:3],
            },
            "career_entries": entries_summary,
            "star_polishes": polishes_summary,
            "culture_claims": [
                c.claim for c in research_bundle.company_research.culture_claims[:5]
            ],
        },
        default=str,
    )

    return await call_agent(
        agent_name="cv_tailor",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=CVOutput,
        model=settings.opus_model_id,
        effort="xhigh",
        post_validate=_make_post_validate(citation_ctx),
    )
