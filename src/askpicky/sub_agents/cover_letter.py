"""Phase 4 — Cover Letter Writer.

Source-grounded prose with inline citation-grounded output. Replaces
the old Anthropic Citations API path (removed 2026-05-25). Now uses
`call_agent` with inline document context and structured JSON output.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..citation_docs import build_document_context
from ..config import settings
from ..llm import AgentCallFailed, call_agent
from ..prompts import load_prompt
from ..schemas import (
    CareerEntry,
    Citation,
    CoverLetterOutput,
    ExtractedJobDescription,
    ResearchBundle,
    STARPolish,
    UserProfile,
    WritingStyleProfile,
)
from ..validators.banned_phrases import contains_banned

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_BASE = load_prompt("cover_letter")
SYSTEM_PROMPT = _SYSTEM_PROMPT_BASE + (
    "\n\nOUTPUT FORMAT:\n"
    "Emit valid JSON matching the CoverLetterOutput schema. The 'paragraphs' "
    "field is a list of paragraph strings. The 'addressed_to' field is the "
    "salutation. Every concrete claim about the company, role, or your own "
    "experience MUST cite a source document by its index number using this "
    "format in the citation array: "
    '{"doc_index": <int>, "excerpt": "<verbatim text from document>"}.\n'
    "Do not output Markdown, only JSON.\n"
)


class _CoverLetterBody(BaseModel):
    addressed_to: str
    paragraphs: list[str]
    citations: list[dict] = []


async def generate(
    jd: ExtractedJobDescription,
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
    style_profile: WritingStyleProfile,
    star_material: Optional[list[STARPolish]] = None,
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
        jd.hiring_manager_name
        if jd.hiring_manager_named and jd.hiring_manager_name
        else "Hiring Team"
    )

    polishes_summary = []
    if star_material:
        for p in star_material:
            polishes_summary.append({
                "question": p.question,
                "action": p.action.text,
                "result": p.result.text,
            })

    # Build inline document context
    context_text, citation_map = build_document_context(
        bundle=research_bundle,
        career_entries=retrieved_entries,
    )

    user_input = json.dumps(
        {
            "role": jd.role_title,
            "company": company.company_name,
            "addressing_to": hiring_manager,
            "jd_required_skills": jd.required_skills[:8],
            "jd_specificity_signals": jd.specificity_signals[:5],
            "user_name": user.name,
            "user_motivations": user.motivations[:5],
            "writing_style": {
                "hint": style_hint,
                "signature_patterns": style_profile.signature_patterns[:5],
                "avoided_patterns": style_profile.avoided_patterns[:5],
                "examples": style_profile.examples[:3],
            },
            "star_polishes": polishes_summary,
            "instruction": (
                "Write a 250-380 word UK cover letter. 3-4 paragraphs. "
                "Cite every concrete claim by document index from the "
                "source documents above."
            ),
        },
        default=str,
    )

    full_input = context_text + "\n\n---\n\n" + user_input

    def _post_validate(parsed: _CoverLetterBody) -> list[str]:
        body_text = " ".join(parsed.paragraphs)
        failures: list[str] = [
            f"Banned phrase in cover letter: '{p}'"
            for p in contains_banned(body_text)
        ]
        wc = len(body_text.split())
        if not (200 <= wc <= 450):
            failures.append(f"word_count {wc} outside 200-450 range")
        if not parsed.citations:
            failures.append(
                "Cover letter produced 0 citations — must cite at least "
                "one source document."
            )
        return failures

    from ..voice import compose_system_prompt
    layered_prompt = compose_system_prompt(
        base_prompt=SYSTEM_PROMPT,
        persona="thought_partner",
    )

    parsed = await call_agent(
        agent_name="cover_letter",
        system_prompt=layered_prompt,
        user_input=full_input,
        output_schema=_CoverLetterBody,
        max_retries=1,
        post_validate=_post_validate,
    )

    body_text = " ".join(parsed.paragraphs)

    # Project model-emitted citations to domain Citation schema
    citations = []
    for raw in parsed.citations:
        idx = raw.get("doc_index", -1)
        info = citation_map.get(idx, {})
        if not info:
            logger.warning("cover_letter: citation doc_index %d not found in map", idx)
            continue
        citations.append(Citation(
            kind=info["kind"],
            url=info.get("url"),
            verbatim_snippet=raw.get("excerpt"),
            data_field=info.get("gov_field"),
            entry_id=info.get("entry_id"),
        ))

    return CoverLetterOutput(
        addressed_to=hiring_manager,
        paragraphs=parsed.paragraphs,
        citations=citations,
        word_count=len(body_text.split()),
    )
