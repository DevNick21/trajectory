"""Phase 0 — Triage before verdict (architecture gap #4).

A single Haiku call (~$0.02) classifies every forward_job as
SERIOUS / EXPLORATORY / DEFINITE_PASS before the full Phase 1
pipeline runs. Only SERIOUS gets the full verdict; the other
two get lighter treatment. This is the single biggest cost-leverage
move in the codebase.

Gated by `settings.enable_triage_before_verdict`.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import (
    CareerEntry,
    ExtractedJobDescription,
    TriageResult,
    UserProfile,
)

logger = logging.getLogger(__name__)


TRIAGE_SYSTEM_PROMPT = """You classify a forwarded job URL for a UK job-search assistant.

Given the job description text and the user's profile, classify the
forward as one of three categories:

SERIOUS — this is a genuine application the user should evaluate
  deeply. The role aligns with their career, the company is a real
  employer, the JD has specific details. Run the full verdict.

EXPLORATORY — the user is browsing. The role is tangentially
  relevant but not a tight fit, OR the JD is too vague to tell,
  OR the company is unknown. Run the verdict but with medium
  effort and surface the uncertainty.

DEFINITE_PASS — obviously not worth the user's time. The role is
  seniority-mismatched, completely wrong field, clearly a ghost
  post, or the salary (if posted) is way below floor. Skip the
  full verdict and tell the user quickly.

RULES:

1. DEFAULT TO SERIOUS when genuinely uncertain. A false
   DEFINITE_PASS that skips the verdict on a real role is worse
   than a false SERIOUS that over-spends $1.

2. DEFINITE_PASS only when the mismatch is OBVIOUS from the JD
   alone — no research needed. Examples:
   - Junior role for a Principal engineer
   - "Marketing Manager" for a Software Engineer
   - Posted salary £25k when user floor is £60k
   - JD is 2 sentences with no duties listed

3. EXPLORATORY when the JD is vague but the domain is right.
   "Exciting opportunity at fast-growing startup" with no tech
   stack listed but in the user's field.

4. Consider the user's visa status — visa holders should bias
   toward SERIOUS because the sponsor check is binary and
   consequential.

5. Consider the user's urgency — HIGH or CRITICAL urgency users
   should bias toward SERIOUS because skipping a real role costs
   more than an Opus call.

OUTPUT: Valid JSON matching TriageResult schema. No prose outside JSON."""


def _fast_fail_classify(jd_text: str, user: UserProfile) -> Optional[TriageResult]:
    """Deterministic tier-0: catch obvious DEFINITE_PASS cases before the
    Haiku call. Zero cost, zero latency. Returns None when the case
    isn't obvious — caller proceeds to the Haiku classifier."""

    # Empty or near-empty JD
    if len(jd_text.strip()) < 60:
        return TriageResult(
            classification="DEFINITE_PASS",
            reasoning_brief="JD is too short to evaluate (under 60 characters).",
            obvious_signals=["trivial_jd"],
        )

    return None


async def classify(
    jd: ExtractedJobDescription,
    user: UserProfile,
    retrieved_entries: Optional[list[CareerEntry]] = None,
) -> TriageResult:
    """Run the triage classifier: tier-0 deterministic first, then Haiku
    if needed. Gated by `settings.enable_triage_before_verdict`."""
    if not settings.enable_triage_before_verdict:
        return TriageResult(
            classification="SERIOUS",
            reasoning_brief="Triage disabled — all forwards get full verdict.",
        )

    # Tier-0: catch obvious DEFINITE_PASS before the LLM call
    tier0 = _fast_fail_classify(jd.jd_text_full, user)
    if tier0 is not None:
        return tier0

    entries_json = (
        json.dumps(
            [{"kind": e.kind, "raw_text": e.raw_text[:300]} for e in (retrieved_entries or [])[:5]],
            default=str,
        )
        if retrieved_entries
        else "[]"
    )

    user_input = json.dumps(
        {
            "job_description": {
                "role_title": jd.role_title,
                "seniority_signal": jd.seniority_signal,
                "soc_code_guess": jd.soc_code_guess,
                "salary_band": jd.salary_band,
                "required_years_experience": jd.required_years_experience,
                "required_skills": jd.required_skills,
                "specificity_signals": jd.specificity_signals[:5],
                "jd_text_first_500": jd.jd_text_full[:500],
            },
            "user_profile": {
                "user_type": user.user_type,
                "current_title": getattr(user, "current_title", None),
                "years_experience": getattr(user, "years_experience", None),
                "salary_floor": user.salary_floor,
                "visa_status": user.visa_status if hasattr(user, "visa_status") else None,
                "urgency": getattr(user, "urgency", "MEDIUM"),
            },
            "retrieved_career_entries": entries_json,
        },
        default=str,
    )

    return await call_agent(
        agent_name="triage",
        system_prompt=TRIAGE_SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=TriageResult,
        effort="low",
        max_retries=1,
        priority="NORMAL",
    )
