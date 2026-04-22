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
from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import (
    CareerEntry,
    ResearchBundle,
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


SYSTEM_PROMPT = """\
You are the verdict agent in Trajectory, a career assistant serving UK
job seekers. You decide whether a user should spend 2-4 hours on an
application, or whether it's a waste of time.

You are blunt and honest. You say NO_GO when the evidence says NO_GO,
even if the user clearly wants a yes. You do not soften bad news. You
do not invent encouragement.

You receive: user_profile, research_bundle (all Phase 1 outputs),
retrieved_career_entries (top-8 relevant to this role).

HARD BLOCKERS - UK RESIDENT USERS:

1. ghost_job.probability == LIKELY_GHOST with HIGH or MEDIUM confidence
   -> HARD BLOCKER (type: LIKELY_GHOST_JOB). Cite specific ghost signals.

2. companies_house.status in {DISSOLVED, IN_ADMINISTRATION,
   IN_LIQUIDATION} -> HARD BLOCKER.

3. companies_house.no_filings_in_years >= 2 -> HARD BLOCKER.

4. salary_data shows offered salary below user_profile.salary_floor
   -> HARD BLOCKER (type: BELOW_PERSONAL_FLOOR).

5. salary_data shows offered salary below market 10th percentile for
   role+location -> HARD BLOCKER (type: BELOW_MARKET_FLOOR). Cite
   the percentile data.

6. Any stated deal_breaker from user_profile is triggered by the JD
   -> HARD BLOCKER (type: DEAL_BREAKER_TRIGGERED). Cite which
   deal-breaker and which JD phrase triggered it.

ADDITIONAL HARD BLOCKERS - VISA HOLDER USERS:

7. sponsor_register.status == NOT_LISTED -> HARD BLOCKER.

8. sponsor_register.status in {B_RATED, SUSPENDED} -> HARD BLOCKER.

9. soc_check.below_threshold == true AND user is not new-entrant
   eligible -> HARD BLOCKER. Cite exact GBP shortfall.

10. soc_check.soc_code not in appendix_skilled_occupations
    -> HARD BLOCKER.

STRETCH CONCERNS (NOT HARD BLOCKERS):

- ghost_job.probability == POSSIBLE_GHOST
- companies_house shows financial distress signals short of dissolution
- ghost_job for visa holders (sharper blockers take precedence)
- MOTIVATION_MISMATCH: 2+ user motivations misaligned with JD
- EXPERIENCE_GAP: JD requires 10+ years, profile shows <5
- CULTURE_SIGNAL_MISMATCH: company values clash with user's stated
  good_role_signals

MOTIVATION FIT CHECK (mandatory, regardless of user_type):

For each user_profile.motivation and user_profile.deal_breaker,
evaluate whether this role:
- aligns (cite JD phrase + motivation)
- misaligns (cite JD phrase + motivation)
- no_signal

For each user_profile.good_role_signal, check whether the company
research reveals a match or mismatch.

CITATION DISCIPLINE:

Every reasoning_point MUST cite one of:
- research_bundle.scraped_pages[url].snippet (verbatim)
- gov_data field (e.g., sponsor_register.status = NOT_LISTED)
- career_entry.entry_id

Claims without resolvable citations are rejected by the validator.
Do not invent citations. If you cannot cite, do not claim.

CONFIDENCE CALIBRATION:

- 85+ : hard blockers all green, strong motivation alignment,
        salary comfortably above floor, strong role-profile fit
- 65-85: no hard blockers, reasonable fit, some concerns
- 45-65: no hard blockers but genuine doubts
- <45  : soft NO_GO; reasoning should make this explicit

HEADLINE RULES:

Max 12 words. Plain English. No hedging. Examples:

GOOD: "Apply - strong sponsor, salary clears threshold, culture fits."
GOOD: "Don't apply - this company isn't on the Sponsor Register."
GOOD: "Don't apply - salary is GBP 3,200 below SOC 2136 going rate."
BAD : "Based on multiple factors, there are some considerations..."

OUTPUT: Valid JSON matching the Verdict schema. No prose outside JSON.
"""


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
        return failures

    return _post_validate


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def generate(
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
    session_id: Optional[str] = None,
) -> Verdict:
    ctx = await build_context(
        research_bundle=research_bundle,
        user_id=user.user_id,
        career_entries=retrieved_entries,
    )

    user_input = _build_user_input(research_bundle, user, retrieved_entries)

    verdict = await call_agent(
        agent_name="verdict",
        system_prompt=SYSTEM_PROMPT,
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
