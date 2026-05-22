"""Phase 2 — Verdict (keystone agent).

System prompt verbatim from AGENTS.md §6.

Post-generation validation (CLAUDE.md Rule 2 + AGENTS.md §6):
  1. Every reasoning_point.citation resolves against the research bundle,
     gov data, or career store.
  2. If decision == "GO" but any hard_blocker is present, flip to NO_GO
     and log the inconsistency.
  3. headline <= 12 words (enforced by the Pydantic validator).
  4. At least 3 reasoning points.
  5. Up to 2 regeneration retries with validator feedback, then fail loud.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..prompts import load_prompt
from ..schemas import (
    CareerEntry,
    Citation,
    HardBlocker,
    MotivationFitReport,
    ReasoningPoint,
    ResearchBundle,
    StretchConcern,
    UserProfile,
    Verdict,
)
from ..validators.citations import (
    ValidationContext,
    build_context,
    validate_output,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompt (verbatim from AGENTS.md §6)
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = load_prompt("verdict")


# A6 / A5: guidance appended to SYSTEM_PROMPT when source_status or
# sources_truncated are in play on this bundle. Kept outside the
# prompt file because the text is only meaningful when the fields
# are populated — leaving it always-on would add noise to the
# baseline prompt.
_SOURCE_STATUS_GUIDANCE = """

## Partial-data caveats (read before reasoning)

Phase 1 sub-agents tag their output with `source_status`:
  - `OK` — we successfully reached the source and have a real reading.
  - `UNREACHABLE` — we attempted the lookup (Sponsor Register, SOC check,
    salary data, etc.) but the upstream API failed or timed out. Treat
    as "I don't know." Do NOT invent a reading and do NOT claim
    "no sponsor license found" when the register was merely unreachable.
    Downgrade confidence and surface the uncertainty in reasoning.
  - `NO_DATA` — we reached the source and it genuinely has nothing
    (e.g., company not on Sponsor Register). This IS a reading.
  - `STALE` — we have data but it's older than the freshness window
    for that source. Usable, but flag the vintage in reasoning.

`research_bundle.sources_truncated` lists fields whose text was
truncated by the content shield before you saw it. When non-empty,
add a reasoning point acknowledging that your view of the JD or
company page was partial, and downgrade confidence by ~10 points.
""".strip()


# ---------------------------------------------------------------------------
# Input serialisation
# ---------------------------------------------------------------------------


def _serialise_user(user: UserProfile) -> dict:
    # Drop the two big immutable timestamps — nothing in the prompt uses
    # them, and we want the input JSON compact.
    data = user.model_dump(mode="json")
    data.pop("created_at", None)
    data.pop("updated_at", None)
    return data


def _serialise_bundle(bundle: ResearchBundle) -> dict:
    # Strip scraped_pages[].text to short previews — the model doesn't need
    # the raw page text to cite, because citations go through verbatim
    # snippets it already selected. The validator re-reads full text from
    # the bundle, not the LLM output.
    data = bundle.model_dump(mode="json")
    cr = data.get("company_research", {})
    pages = cr.get("scraped_pages", [])
    for p in pages:
        if isinstance(p.get("text"), str) and len(p["text"]) > 1_200:
            p["text"] = p["text"][:1_200] + "... [TRUNCATED]"
    return data


def _serialise_entries(entries: list[CareerEntry]) -> list[dict]:
    return [
        {
            "entry_id": e.entry_id,
            "kind": e.kind,
            "raw_text": e.raw_text[:800],
        }
        for e in entries
    ]


def _build_user_input(
    bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
) -> str:
    payload = {
        "user_profile": _serialise_user(user),
        "research_bundle": _serialise_bundle(bundle),
        "retrieved_career_entries": _serialise_entries(retrieved_entries),
    }
    return json.dumps(payload, default=str, indent=2)


# ---------------------------------------------------------------------------
# Post-validation: GO-with-blocker flip + reasoning-point floor
# ---------------------------------------------------------------------------


def _enforce_no_go_with_blockers(v: Verdict) -> Verdict:
    """CLAUDE.md Rule 2: a GO verdict with any hard blocker is a programmatic
    error. Flip to NO_GO and log.
    """
    if v.decision == "GO" and v.hard_blockers:
        logger.error(
            "Verdict returned GO despite %d hard blocker(s): %s — flipping to NO_GO.",
            len(v.hard_blockers),
            [b.type for b in v.hard_blockers],
        )
        return v.model_copy(
            update={
                "decision": "NO_GO",
                "confidence_pct": min(v.confidence_pct, 60),
            }
        )
    return v


def _make_post_validate(ctx: ValidationContext):
    def _post_validate(v: Verdict) -> list[str]:
        failures: list[str] = []
        failures.extend(validate_output(v, ctx))
        if len(v.reasoning) < 3:
            failures.append(
                f"verdict.reasoning has {len(v.reasoning)} points; "
                "at least 3 required."
            )
        # CLAUDE.md Rule 2: a GO verdict with any hard blocker is an error.
        # Reject here so call_agent retries with feedback rather than
        # forcing us to flip post-hoc (the flip is still applied by
        # _enforce_no_go_with_blockers as a belt-and-braces guard in case
        # all retries return the same inconsistent decision).
        if v.decision == "GO" and v.hard_blockers:
            blocker_types = [b.type for b in v.hard_blockers]
            failures.append(
                "Verdict.decision is GO but hard_blockers is non-empty "
                f"({blocker_types}); a GO with any hard blocker is not "
                "permitted. Either remove the blocker (if it does not apply) "
                "or switch decision to NO_GO."
            )
        return failures

    return _post_validate


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def _mock_verdict(user: UserProfile, bundle: ResearchBundle) -> Verdict:
    """Fixture verdict used when SMOKE_TEST_MOCK=1.

    Debug loops on smoke_test.py would otherwise burn Opus 4.7 xhigh on
    every iteration — roughly $0.50–$1.50 per call. Gating the real API
    call behind an env var preserves the full wiring of call_agent,
    post_validate, and _enforce_no_go_with_blockers for integration runs
    while letting local iteration stay free.
    """
    role = bundle.extracted_jd.role_title or "this role"
    company = bundle.company_research.company_name or "this company"
    pages = bundle.company_research.scraped_pages
    first_page_url = pages[0].url if pages else "about:blank"
    first_snippet = (pages[0].text[:60] if pages and pages[0].text else "fixture")
    citation = Citation(
        kind="url_snippet",
        url=first_page_url,
        verbatim_snippet=first_snippet,
    )
    return Verdict(
        decision="GO",
        confidence_pct=72,
        headline="Apply - fixture verdict, no real Opus call.",
        reasoning=[
            ReasoningPoint(
                claim=f"Fixture verdict for {role} at {company}.",
                supporting_evidence="SMOKE_TEST_MOCK=1 — no real Opus call.",
                citation=citation,
            ),
            ReasoningPoint(
                claim="All hard-blocker sources evaluated to benign in the fixture.",
                supporting_evidence="bundle.sponsor_status / soc_check / ghost_job",
                citation=citation,
            ),
            ReasoningPoint(
                claim="Motivation and voice profiles wired through end-to-end.",
                supporting_evidence="style_profile + retrieved_entries both bound.",
                citation=citation,
            ),
        ],
        hard_blockers=[],
        stretch_concerns=[],
        motivation_fit=MotivationFitReport(
            motivation_evaluations=[],
            deal_breaker_evaluations=[],
            good_role_signal_evaluations=[],
        ),
    )


def _mock_enabled() -> bool:
    return os.getenv("SMOKE_TEST_MOCK", "").lower() in {"1", "true", "yes"}


async def generate(
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
    session_id: Optional[str] = None,
) -> Verdict:
    if _mock_enabled():
        logger.warning(
            "SMOKE_TEST_MOCK=1 — returning fixture verdict without calling "
            "the Anthropic API. Unset the env var to exercise real Opus."
        )
        return _enforce_no_go_with_blockers(_mock_verdict(user, research_bundle))

    ctx = await build_context(
        research_bundle=research_bundle,
        user_id=user.user_id,
        career_entries=retrieved_entries,
    )

    user_input = _build_user_input(research_bundle, user, retrieved_entries)

    system_prompt = SYSTEM_PROMPT
    if settings.enable_source_status_verdict:
        # Append only when the flag is on — lets us revert to the
        # pre-A6 behaviour (verdict ignores source_status) without
        # redeploying the prompt file.
        system_prompt = SYSTEM_PROMPT + "\n\n" + _SOURCE_STATUS_GUIDANCE

    verdict = await call_agent(
        agent_name="verdict",
        system_prompt=system_prompt,
        user_input=user_input,
        output_schema=Verdict,
        model=settings.opus_model_id,
        effort="xhigh",
        max_retries=2,
        session_id=session_id,
        priority="CRITICAL",
        post_validate=_make_post_validate(ctx),
    )

    return _enforce_no_go_with_blockers(verdict)
