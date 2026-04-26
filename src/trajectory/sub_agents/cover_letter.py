"""Phase 4 — Cover Letter Writer.

Source-grounded prose with first-party Citations API attached.
System prompt verbatim from AGENTS.md §13. Migrated from `call_agent`
(structured tool_use) to `call_with_citations` on 2026-04-25
(PROCESS Entry 43, Workstream B/D).

The Citations API guarantees verbatim_snippet validity at the SDK
boundary, so the `validate_output` post-hook on citations becomes
unnecessary. Banned-phrase + word-count post-validation stays.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..citation_docs import build_documents_for_bundle
from ..config import settings
from ..llm import CitationResult, call_with_citations
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

logger = logging.getLogger(__name__)

# Original cover-letter system prompt + a short addendum that asks the
# model to emit paragraphs separated by blank lines (the only structuring
# requirement we still need now that Citations replaces tool_use).
_SYSTEM_PROMPT_BASE = load_prompt("cover_letter")
SYSTEM_PROMPT = _SYSTEM_PROMPT_BASE + (
    "\n\nOUTPUT FORMAT:\n"
    "Emit the cover letter as plain prose. Each paragraph on its own, "
    "separated by a blank line. Do not output Markdown, JSON, or any "
    "wrapper structure. Cite source documents inline using the Citations "
    "API — every concrete claim about the company, role, or your own "
    "experience MUST attach a verbatim cited_text. The first line of your "
    "output must be the salutation (`Dear ...`); the last must be the "
    "signoff line.\n"
)


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
        jd.hiring_manager_name if jd.hiring_manager_named and jd.hiring_manager_name
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
                "Cite every concrete claim from the supplied documents."
            ),
        },
        default=str,
    )

    documents, idx_maps = build_documents_for_bundle(
        bundle=research_bundle,
        career_entries=retrieved_entries,
    )

    def _post_validate(r: CitationResult) -> list[str]:
        body_local = r.body.strip()
        failures: list[str] = [
            f"Banned phrase in cover letter: '{p}'"
            for p in contains_banned(body_local)
        ]
        wc = len(body_local.split())
        if not (200 <= wc <= 450):
            failures.append(f"word_count {wc} outside 200-450 range")
        # Use raw SDK citations here — projection failures (idx_maps
        # mismatch) are caller-side and not recoverable by re-prompting.
        if not r.raw_citations:
            failures.append(
                "Cover letter produced 0 citations — Citations API should "
                "have attached at least one cited_text per paragraph."
            )
        return failures

    result = await call_with_citations(
        agent_name="cover_letter",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        documents=documents,
        model=settings.opus_model_id,
        effort="xhigh",
        max_retries=1,
        post_validate=_post_validate,
    )

    body = result.body.strip()

    # Parse paragraphs (split on blank lines, keep non-empty).
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    if len(paragraphs) < 2:
        # Fallback: split on single newline if blank-line split failed.
        paragraphs = [p.strip() for p in body.split("\n") if p.strip()]

    # Project SDK citations into our domain Citation schema. Projection
    # failures only — model-side validity (banned phrases, word count,
    # citation presence) is enforced by `_post_validate` above.
    citations: list[Citation] = []
    for raw in result.raw_citations:
        try:
            citations.append(Citation.from_api(raw, **idx_maps))
        except Exception as exc:
            logger.warning(
                "cover_letter: skipping citation that failed projection: %s (%s)",
                raw, exc,
            )

    return CoverLetterOutput(
        addressed_to=hiring_manager,
        paragraphs=paragraphs,
        citations=citations,
        word_count=len(body.split()),
    )
