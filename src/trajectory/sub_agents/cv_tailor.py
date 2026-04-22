"""Phase 4 — CV Tailor.

Produces a CV tailored to a specific role, grounded in career history.
System prompt verbatim from AGENTS.md §12.
"""

from __future__ import annotations

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

SYSTEM_PROMPT = """\
Produce a CV tailored to a specific UK job.

You receive:
- extracted_jd
- company_research
- user_profile
- retrieved_career_entries (top-12 most relevant to this role)
- writing_style_profile
- any role-specific raw material from Phase 3 Q&A polishes

STRUCTURE (UK convention):
- Name + contact (from user_profile)
- 2-3 line professional summary (in user's voice)
- Experience section (reverse-chronological), 3-5 bullets per role
- Education
- Skills (targeted to JD)
- Optional: Projects (if user has project_notes worth surfacing)

HARD RULES:

1. Every bullet cites either a specific career_entry or a specific JD
   requirement the bullet addresses. Use inline cite markers
   [ce:entry_id] in the bullet text during generation — the formatter
   strips them later but the validator checks them.

2. Never invent metrics. If the user's career_entry says "improved
   eval latency significantly" and doesn't have a number, the CV
   bullet doesn't get a number.

3. Write in the user's voice per writing_style_profile. Use
   signature_patterns. Never use avoided_patterns or banned_phrases.

4. Reorder and rephrase existing career_entries to highlight
   relevance to THIS job. Do not duplicate across bullets.

5. Keep to 2 pages max. Prioritise recency + relevance.

6. UK spelling (optimise, centre, programme, etc.) unless user's
   writing_style_profile.examples clearly use US spelling.

7. Professional summary must not be boilerplate. It must mention at
   least one specific thing from this role's JD and at least one
   specific thing from the user's career that matches.

OUTPUT: Valid JSON matching CVOutput schema (structured sections
that render to Markdown/PDF downstream).
"""

_CE_MARKER = re.compile(r"\[ce:[^\]]+\]")


def _post_validate(cv: CVOutput) -> list[str]:
    failures: list[str] = []
    all_text_parts = [cv.professional_summary]
    for role in cv.experience:
        for b in role.bullets:
            all_text_parts.append(b.text)
    all_text = " ".join(all_text_parts)
    # Strip cite markers before banned-phrase check
    clean = _CE_MARKER.sub("", all_text)
    for phrase in contains_banned(clean):
        failures.append(f"Banned phrase in CV: '{phrase}'")
    return failures


async def generate(
    jd: ExtractedJobDescription,
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
    style_profile: WritingStyleProfile,
    star_material: Optional[list[STARPolish]] = None,
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
        post_validate=_post_validate,
    )
