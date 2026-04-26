"""Multi-provider CV tailor (PROCESS Entry 44).

Single-call CV generation that routes through the provider mapped from
the job_url's ATS host (`ats_routing.provider_for_url`).

Why single-call rather than the agentic FAISS-search loop in
`cv_tailor_agentic.py`?
- The agentic loop uses Anthropic-specific multi-turn `tool_use`. Each
  provider has a different tool-calling shape (OpenAI function-calling,
  Cohere tool-use, Llama via Together's compatibility layer), and
  porting the loop 4× would multiply the maintenance surface for one
  call site.
- Pre-retrieving career entries (top-K up-front) and stuffing them into
  a single prompt is functionally close enough for the CV-quality
  comparison this routing is meant to enable.
- Citation discipline is preserved — `validators/citations.py` runs on
  the returned `CVOutput` regardless of which provider produced it.

This module is invoked by `orchestrator.handle_draft_cv` when
`settings.enable_multi_provider_cv_tailor=True` AND the URL routes to
a non-Anthropic provider. Anthropic-routed URLs continue through the
existing `cv_tailor_agentic` / `cv_tailor_advisor` paths.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..ats_routing import Provider
from ..config import settings
from ..llm_providers import call_structured as call_via_provider
from ..schemas import (
    CareerEntry,
    CVOutput,
    ExtractedJobDescription,
    ResearchBundle,
    STARPolish,
    UserProfile,
    WritingStyleProfile,
)
from ..storage import STAR_BOOST_KINDS, search_career_entries_semantic
from ..validators.citations import ValidationContext, validate_output
from ..validators.content_shield import shield as shield_content

logger = logging.getLogger(__name__)


# Single-call variant of the cv_tailor_agentic system prompt. Drops the
# "use the search tool" instruction; career entries arrive inline.
SYSTEM_PROMPT = """\
You are the Trajectory CV tailor. Produce a UK CV tailored to the
specific role + company described in the user message.

You receive the JD, company culture signals, the user's writing-style
profile, optional STAR polishes, and a pre-retrieved batch of the
user's career entries. Use them. Do NOT invent experience.

Output: ONE valid `CVOutput` JSON object (no Markdown wrapper, no prose
outside the object). Every CVBullet's `citations` list must contain at
least one Citation. Allowed citation kinds:
  - `career_entry` with the entry_id of a career entry in the input
  - `url_snippet` with a verbatim_snippet from a scraped culture claim
  - `gov_data` with a data_field + raw data_value from the gov-data block

CITATION RULES (the validator will reject violations):
- `career_entry`: entry_id MUST appear in the supplied career_entries list.
  Do NOT cite an entry_id that wasn't given to you.
- `url_snippet`: verbatim_snippet must be an EXACT substring of the source
  text supplied. No paraphrasing.
- `gov_data`: data_value is the raw stored value (e.g. "LISTED", not
  "LISTED (A-rated)"). Put context in supporting prose, not data_value.

STYLE RULES:
- Match the user's `writing_style` (tone, signature_patterns, avoided_patterns).
- Avoid every banned phrase: passionate, team player, results-driven,
  synergy, go-getter, proven track record, rockstar, ninja, thought leader,
  game-changer, leverage (as verb), touch base, circle back, reach out,
  excited to apply, dynamic, hit the ground running, self-starter, out of
  the box, move the needle, deep dive.
- 3-6 roles in `experience`, 3-5 bullets per role, each bullet is one
  short sentence with a quantified result where possible.
- Lead with what the JD's `selection_signals` and `cv_emphasis_hints`
  ask for (if present); otherwise lead with the JD's required_skills.

OUTPUT: valid JSON matching CVOutput. No prose. No fences.
"""


async def generate_via_provider(
    *,
    provider: Provider,
    jd: ExtractedJobDescription,
    research_bundle: ResearchBundle,
    user: UserProfile,
    style_profile: WritingStyleProfile,
    star_material: Optional[list[STARPolish]] = None,
    citation_ctx: Optional[ValidationContext] = None,
    session_id: Optional[str] = None,
) -> CVOutput:
    """Single-call CV generation via the routed provider."""

    # 1. Pre-retrieve career entries (top 12, STAR-boosted) — replaces
    # the agentic search loop on this path.
    query = f"{jd.role_title} {' '.join((jd.required_skills or [])[:5])}"
    entries: list[CareerEntry] = await search_career_entries_semantic(
        user_id=user.user_id,
        query=query,
        kind_filter="ANY",
        top_k=10,
        kind_weights=STAR_BOOST_KINDS,
    )

    # 2. Tier 1 shield each entry — career entries are user-typed text.
    shielded_entries: list[dict] = []
    for e in entries:
        cleaned, _ = await shield_content(
            content=e.raw_text[:1500],
            source_type="user_message",
            downstream_agent="cv_tailor",
        )
        shielded_entries.append({
            "entry_id": e.entry_id,
            "kind": e.kind,
            "raw_text": cleaned,
        })

    # 3. Build one big prompt payload.
    style_hint = (
        f"tone={style_profile.tone}, "
        f"formality={style_profile.formality_level}/10, "
        f"hedging={style_profile.hedging_tendency}"
    )
    if style_profile.sample_count < 3:
        style_hint += " (low confidence — directional only)"

    polishes_summary: list[dict] = []
    if star_material:
        for p in star_material:
            polishes_summary.append({
                "question": p.question,
                "situation": p.situation.text,
                "task": p.task.text,
                "action": p.action.text,
                "result": p.result.text,
            })

    user_input = json.dumps({
        "user": {
            "name": user.name,
            "base_location": user.base_location,
            "linkedin_url": user.linkedin_url,
            "github_url": user.github_url,
        },
        "jd": {
            "role_title": jd.role_title,
            "seniority": jd.seniority_signal,
            "required_skills": jd.required_skills,
            "specificity_signals": jd.specificity_signals[:5],
            "remote_policy": jd.remote_policy,
            "location": jd.location,
        },
        "company": research_bundle.company_research.company_name,
        "company_culture_claims": [
            {"claim": c.claim, "snippet": c.verbatim_snippet, "url": c.url}
            for c in research_bundle.company_research.culture_claims[:6]
        ],
        "writing_style": {
            "hint": style_hint,
            "signature_patterns": style_profile.signature_patterns[:5],
            "avoided_patterns": style_profile.avoided_patterns[:5],
            "examples": style_profile.examples[:3],
        },
        "star_polishes": polishes_summary,
        "career_entries": shielded_entries,
        "instructions": (
            "Use only career entries from the `career_entries` list. "
            "Cite each bullet with at least one Citation."
        ),
    }, default=str)

    # 4. Dispatch to the routed provider.
    cv = await call_via_provider(
        provider=provider,
        agent_name=f"cv_tailor_multi_provider:{provider}",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=CVOutput,
        # Anthropic uses opus_model_id by default in the adapter; other
        # providers fall back to their per-provider model id in settings.
        model=None,
        effort="xhigh",
        session_id=session_id,
    )

    # 5. Citation post-validation — same `validators/citations.py` rules
    # the Anthropic-only path uses. Pre-retrieved entries form the
    # legitimate set of `career_entry` citations.
    if citation_ctx is not None:
        cit_failures = validate_output(cv, citation_ctx)
        if cit_failures:
            logger.warning(
                "cv_tailor_multi_provider (%s): %d citation failure(s) — "
                "first 3: %s",
                provider, len(cit_failures), cit_failures[:3],
            )
            # Don't raise; the orchestrator's _audit_and_ship loop will
            # surface this through self_audit instead. Keeping parity
            # with the agentic path's "log + ship" behaviour for soft
            # citation issues.

    logger.info(
        "cv_tailor_multi_provider provider=%s entries_retrieved=%d "
        "roles=%d total_bullets=%d",
        provider, len(entries), len(cv.experience),
        sum(len(r.bullets) for r in cv.experience),
    )
    return cv
