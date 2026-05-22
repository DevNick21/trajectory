"""Managed cover letter generator (PROCESS Entry 45).

Live cover-letter generation that goes back to the company's careers /
about / values / engineering-blog pages at draft time and pulls
fresh, narrowly-targeted snippets matched to THIS user's motivations.

Why managed (web-fetch-equipped) instead of just consuming the bundle:
- The bundle's `culture_claims` were extracted at Phase 1 from a generic
  "what's this company about" prompt. A cover-letter-specific live fetch
  can target "values that match THIS user's motivations" — different
  signal density.
- Pages update. A bundle from days ago may have stale culture text;
  a live fetch is current.

Triggered when `settings.enable_managed_cover_letter=True`. Orchestrator
catches any exception and falls back to the in-process
`sub_agents/cover_letter.generate(...)` path so the demo never goes
down on a flaky web fetch.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..config import settings
from ..llm import call_with_tools
from ..prompts import load_prompt
from ..schemas import (
    CareerEntry,
    CoverLetterOutput,
    ExtractedJobDescription,
    ResearchBundle,
    STARPolish,
    UserProfile,
    WritingStyleProfile,
)
from ..server_tools import WEB_FETCH, WEB_SEARCH
from ..validators.banned_phrases import contains_banned
from . import _register_session

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT_BASE = load_prompt("cover_letter")
_LIVE_ADDENDUM = """

## Managed live-research mode (enable_managed_cover_letter=True)

You have Web Search and Web Fetch tools available. Before drafting,
do up to 2 targeted lookups against the COMPANY DOMAIN provided:
  - One: the company's careers / values / about / culture page
  - Two (only if needed): the engineering or product blog OR a stated
    mission document. Skip if the first page gave you enough material.

Hard cap: at most 2 fetches. Move on; the in-bundle company_research
already covers most of what you need — these fetches are top-up
signal, not full replacement.

For each fetched page, identify VERBATIM snippets that align with
THIS user's stated motivations (provided in the prompt). Pages update;
freshly-fetched material beats whatever is in the supplied
research_bundle when they conflict.

CRITICAL — Output `citations` field:

The CoverLetterOutput JSON you emit via emit_structured_output MUST
populate the `citations: list[Citation]` field. Every concrete claim
in your paragraphs needs a corresponding Citation entry. Two valid
shapes:

  {"kind": "url_snippet", "url": "https://...", "verbatim_snippet": "..."}
  {"kind": "career_entry", "entry_id": "<from career_entries[]>"}

The verbatim_snippet for a url_snippet citation MUST be character-for-
character what appeared in the fetched page — the post-validator
checks this. If you didn't fetch it, don't cite it.

A CoverLetterOutput with empty `citations` is a failed output and
will be rejected. Aim for 3-5 citations: 2-3 url_snippets pointing
at the live-fetched company pages, 1-2 career_entry citations for
the "what I'd bring" paragraph.
"""

SYSTEM_PROMPT = _SYSTEM_PROMPT_BASE + _LIVE_ADDENDUM


async def run(
    *,
    jd: ExtractedJobDescription,
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
    style_profile: WritingStyleProfile,
    star_material: Optional[list[STARPolish]] = None,
    session_id: Optional[str] = None,
) -> CoverLetterOutput:
    """Live-web-equipped cover letter generation."""

    company_research = research_bundle.company_research
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

    user_input = json.dumps({
        "role": jd.role_title,
        "company": company_research.company_name,
        "company_domain": company_research.company_domain,
        "addressing_to": hiring_manager,
        "jd_required_skills": jd.required_skills[:8],
        "user_name": user.name,
        "user_motivations": user.motivations[:5],
        "user_good_role_signals": user.good_role_signals[:5],
        "writing_style": {
            "hint": style_hint,
            "signature_patterns": style_profile.signature_patterns[:5],
            "avoided_patterns": style_profile.avoided_patterns[:5],
            "examples": style_profile.examples[:3],
        },
        "career_entries": [
            {"entry_id": e.entry_id, "kind": e.kind, "text": e.raw_text[:400]}
            for e in retrieved_entries[:8]
        ],
        "star_polishes": polishes_summary,
        "instruction": (
            "Use Web Fetch + Web Search to pull fresh culture snippets "
            "that match this user's motivations. Then draft a 250-380 "
            "word UK cover letter, 3-4 paragraphs, every concrete claim "
            "cited."
        ),
    }, default=str)

    def _pv(out: CoverLetterOutput) -> list[str]:
        problems: list[str] = []
        if not out.citations:
            problems.append(
                "citations field is empty. Populate it with at least 3 "
                "Citation entries — typically 2-3 url_snippet citations "
                "pointing at the live-fetched company pages and 1-2 "
                "career_entry citations for the 'what I'd bring' paragraph."
            )
        body = " ".join(out.paragraphs)
        bp = contains_banned(body)
        if bp:
            problems.append(f"banned phrases present: {bp}. Rewrite without them.")
        if not 200 <= out.word_count <= 600:
            problems.append(
                f"word_count {out.word_count} outside 200-600 window. "
                "Aim for ~280-330."
            )
        return problems

    cl = await call_with_tools(
        agent_name="cover_letter_managed",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=CoverLetterOutput,
        server_tools=[WEB_SEARCH, WEB_FETCH],
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
        post_validate=_pv,
    )

    # Banned-phrase post-validation (parity with in-process cover_letter).
    body = " ".join(cl.paragraphs)
    bp = contains_banned(body)
    if bp:
        logger.warning(
            "cover_letter_managed banned phrases (non-fatal): %s", bp,
        )

    logger.info(
        "cover_letter_managed: paragraphs=%d word_count=%d citations=%d",
        len(cl.paragraphs), cl.word_count, len(cl.citations),
    )
    return cl


_register_session("cover_letter_managed", run)
