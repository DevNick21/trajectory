"""Phase 4.5 — Self-Audit.

Audits every Phase 4 output before delivery.
System prompt verbatim from AGENTS.md §16.
"""

from __future__ import annotations

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

SYSTEM_PROMPT = """\
Audit a generated pack component against its source material.

You receive:
- the generated output (CV, cover letter, likely questions, or reply)
- the research bundle it should be grounded in
- the user's writing_style_profile
- the list of career_entries available

Flag any of the following:

1. UNSUPPORTED_CLAIM: a claim without a resolvable citation.

2. CLICHE: use of any banned phrase from the repo's banned list:
   passionate, team player, results-driven, synergy, go-getter,
   proven track record, rockstar, ninja, thought leader,
   game-changer, leverage (verb), touch base, circle back,
   reach out, excited to apply, dynamic, hit the ground running,
   self-starter, out of the box, move the needle, deep dive.

3. HEDGING: defensive phrases like "I believe I can", "I think I
   might", "I would say that I am".

4. COMPANY_SWAP_FAIL: any sentence where swapping the target
   company's name wouldn't change the meaning. Test: replace
   "Monzo" with "Revolut" — does the sentence still read exactly
   the same? If yes, flag. These must be rewritten to cite
   something specific.

5. STYLE_MISMATCH: sentences with style conformance <7/10 to the
   user's WritingStyleProfile. Flag with a proposed rewrite.

For each flag:
- exact offending substring
- flag_type (one of the 5 above)
- proposed_rewrite (grounded in source material)
- citation the rewrite uses

RULES:

1. Do not flag everything. Flag what actually fails. A tight, cited,
   voice-matched document gets an empty flags list.

2. Proposed rewrites must be concrete. "Make this more specific" is
   useless. "Replace with 'Their engineering blog's post on
   eliminating 400ms p99 tails maps directly to my work on the
   clinical RAG retrieval layer' [url+snippet]" is useful.

3. If the generated output has no citations at all, return a
   HARD_REJECT flag — the orchestrator should re-run the generator
   with explicit citation guidance.

OUTPUT: Valid JSON matching SelfAuditReport.
"""

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
