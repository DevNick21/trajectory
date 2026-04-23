"""Phase 4.5 — Self-Audit.

Audits every Phase 4 output before delivery.
System prompt verbatim from AGENTS.md §16.
"""

from __future__ import annotations

from ..prompts import load_prompt

import json
from typing import Optional, Union

from ..config import settings
from ..llm import call_agent
from ..schemas import (
    CVOutput,
    CoverLetterOutput,
    DraftReplyOutput,
    LikelyQuestionsOutput,
    ResearchBundle,
    SelfAuditReport,
    WritingStyleProfile,
)

SYSTEM_PROMPT = load_prompt("self_audit")

GeneratedOutput = Union[CVOutput, CoverLetterOutput, LikelyQuestionsOutput, DraftReplyOutput]


async def run(
    generated: GeneratedOutput,
    research_bundle: Optional[ResearchBundle],
    style_profile: WritingStyleProfile,
    company_name: str,
    session_id: Optional[str] = None,
) -> SelfAuditReport:
    bundle_summary: dict = {}
    if research_bundle:
        bundle_summary = {
            "company": research_bundle.company_research.company_name,
            "culture_claims": [c.claim for c in research_bundle.company_research.culture_claims[:5]],
            "jd_role": research_bundle.extracted_jd.role_title,
            "jd_skills": research_bundle.extracted_jd.required_skills[:10],
        }

    user_input = json.dumps(
        {
            "company_name": company_name,
            "generated_output": generated.model_dump(mode="json"),
            "research_bundle_summary": bundle_summary,
            "writing_style_profile": {
                "tone": style_profile.tone,
                "formality_level": style_profile.formality_level,
                "hedging_tendency": style_profile.hedging_tendency,
                "signature_patterns": style_profile.signature_patterns[:5],
                "avoided_patterns": style_profile.avoided_patterns[:5],
                "examples": style_profile.examples[:3],
            },
        },
        default=str,
    )

    return await call_agent(
        agent_name="self_audit",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=SelfAuditReport,
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
    )


def apply_rewrites(
    text: str, audit: SelfAuditReport
) -> str:
    """Apply proposed rewrites in-place to a text block."""
    for flag in audit.flags:
        if flag.flag_type == "HARD_REJECT":
            continue
        if flag.offending_substring in text and flag.proposed_rewrite:
            text = text.replace(flag.offending_substring, flag.proposed_rewrite, 1)
    return text
