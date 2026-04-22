"""Phase 1 — Ghost Job Detector.

Combines 4 signals into a `GhostJobAssessment`:

  1. STALE_POSTING          — from `extracted_jd.posted_date`
  2. NOT_ON_CAREERS_PAGE    — from `company_research.not_on_careers_page`
  3. VAGUE_JD               — from the Ghost-Job JD Scorer LLM (Opus xhigh)
  4. COMPANY_DISTRESS       — from Companies House status + filings

Combination rules (source: CLAUDE.md "Hard architectural rules" + test spec
in tests/test_ghost_job_combination.py):

  - 2+ HARD signals           -> LIKELY_GHOST, HIGH confidence
  - 1 HARD + >=1 SOFT         -> LIKELY_GHOST, MEDIUM confidence
  - 1 HARD alone              -> POSSIBLE_GHOST, MEDIUM confidence
  - 0 HARD, >=2 SOFT          -> POSSIBLE_GHOST, MEDIUM confidence
  - 0 HARD, 1 SOFT            -> POSSIBLE_GHOST, LOW confidence
  - 0 signals                 -> LIKELY_REAL, HIGH confidence

JD-scorer prompt is verbatim from AGENTS.md §5.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import (
    Citation,
    CompaniesHouseSnapshot,
    CompanyResearch,
    ExtractedJobDescription,
    GhostJobAssessment,
    GhostJobJDScore,
    GhostSignal,
)


# ---------------------------------------------------------------------------
# LLM — JD specificity scorer
# ---------------------------------------------------------------------------


JD_SCORER_SYSTEM_PROMPT = """\
Score a job description for how specific and real it sounds.

Dimensions (rate each 0-1, justify in 1 sentence):

1. Named hiring manager or team lead
2. Specific duty bullets (vs generic boilerplate)
3. Specific tech stack or tools
4. Specific team or department context
5. Specific success metrics or 30/60/90 expectations

Compute specificity_score = sum of the 5 dimensions (0-5).

Also list:
- specificity_signals: concrete JD phrases that feel real
- vagueness_signals: concrete JD phrases that feel boilerplate

RULES:

1. "Competitive salary", "fast-paced environment", "team player",
   "self-starter", "growth opportunity" are all vagueness signals.
2. Named hiring manager only counts if an actual human name or
   specific role (e.g., "reporting to the Head of ML Platform") is
   present.
3. Generic-sounding role titles (e.g., "Software Engineer" with no
   modifier) are not automatically vague - the JD body decides.
4. Output is strict JSON matching GhostJobJDScore.
"""


async def _score_jd(
    jd: ExtractedJobDescription,
    session_id: Optional[str],
) -> GhostJobJDScore:
    return await call_agent(
        agent_name="phase_1_ghost_job_jd_scorer",
        system_prompt=JD_SCORER_SYSTEM_PROMPT,
        user_input=(
            f"ROLE: {jd.role_title}\n"
            f"SENIORITY: {jd.seniority_signal}\n"
            f"HIRING MANAGER NAMED: {jd.hiring_manager_named}"
            f"{f' ({jd.hiring_manager_name})' if jd.hiring_manager_name else ''}\n\n"
            "JD TEXT:\n"
            f"{jd.jd_text_full[:16_000]}"
        ),
        output_schema=GhostJobJDScore,
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# Deterministic signal extraction
# ---------------------------------------------------------------------------


def _stale_signal(jd: ExtractedJobDescription) -> Optional[GhostSignal]:
    if jd.posted_date is None:
        return None
    age_days = (date.today() - jd.posted_date).days
    if age_days < 30:
        return None
    severity = "HARD" if age_days > 60 else "SOFT"
    return GhostSignal(
        type="STALE_POSTING",
        evidence=f"Posted {age_days} days ago ({jd.posted_date.isoformat()}).",
        citation=Citation(
            kind="url_snippet",
            url="",  # JD URL stitched in at caller if available
            verbatim_snippet=f"Posted {jd.posted_date.isoformat()}",
        ),
        severity=severity,
    )


def _careers_page_signal(cr: CompanyResearch) -> Optional[GhostSignal]:
    if not cr.not_on_careers_page:
        return None
    careers_url = cr.careers_page_url or ""
    return GhostSignal(
        type="NOT_ON_CAREERS_PAGE",
        evidence=(
            "Role is not listed on the company's own careers page — a "
            "strong ghost-job signal for a real open req."
        ),
        citation=Citation(
            kind="url_snippet",
            url=careers_url,
            verbatim_snippet="not_on_careers_page=true",
        ),
        severity="HARD",
    )


def _vague_jd_signal(
    jd: ExtractedJobDescription, score: GhostJobJDScore
) -> Optional[GhostSignal]:
    if score.specificity_score >= 2.5:
        return None
    severity = "HARD" if score.specificity_score < 1.5 else "SOFT"
    return GhostSignal(
        type="VAGUE_JD",
        evidence=(
            f"JD specificity score {score.specificity_score:.1f}/5. "
            f"Vagueness: {'; '.join(score.vagueness_signals[:5]) or 'no concrete specifics'}"
        ),
        citation=Citation(
            kind="url_snippet",
            url="",
            verbatim_snippet=(score.vagueness_signals[:1] or [jd.role_title])[0],
        ),
        severity=severity,
    )


def _distress_signal(
    ch: Optional[CompaniesHouseSnapshot],
) -> Optional[GhostSignal]:
    if ch is None:
        return None
    if ch.status in {"DISSOLVED", "IN_ADMINISTRATION", "IN_LIQUIDATION"}:
        return GhostSignal(
            type="COMPANY_DISTRESS",
            evidence=f"Companies House status: {ch.status}.",
            citation=Citation(
                kind="gov_data",
                data_field="companies_house.status",
                data_value=ch.status,
            ),
            severity="HARD",
        )
    if ch.accounts_overdue or ch.no_filings_in_years >= 2 or ch.resolution_to_wind_up:
        detail_bits = []
        if ch.accounts_overdue:
            detail_bits.append("accounts overdue")
        if ch.no_filings_in_years >= 2:
            detail_bits.append(f"no filings in {ch.no_filings_in_years} years")
        if ch.resolution_to_wind_up:
            detail_bits.append("resolution to wind up filed")
        return GhostSignal(
            type="COMPANY_DISTRESS",
            evidence="Companies House distress signals: " + ", ".join(detail_bits),
            citation=Citation(
                kind="gov_data",
                data_field="companies_house.accounts_overdue",
                data_value=str(ch.accounts_overdue).lower(),
            ),
            severity="SOFT",
        )
    return None


# ---------------------------------------------------------------------------
# Combination
# ---------------------------------------------------------------------------


def _combine(signals: list[GhostSignal]) -> tuple[str, str]:
    hard = sum(1 for s in signals if s.severity == "HARD")
    soft = sum(1 for s in signals if s.severity == "SOFT")

    if hard >= 2:
        return "LIKELY_GHOST", "HIGH"
    if hard == 1 and soft >= 1:
        return "LIKELY_GHOST", "MEDIUM"
    if hard == 1:
        return "POSSIBLE_GHOST", "MEDIUM"
    if soft >= 2:
        return "POSSIBLE_GHOST", "MEDIUM"
    if soft == 1:
        return "POSSIBLE_GHOST", "LOW"
    return "LIKELY_REAL", "HIGH"


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


async def score(
    jd: ExtractedJobDescription,
    company_research: CompanyResearch,
    companies_house: Optional[CompaniesHouseSnapshot] = None,
    session_id: Optional[str] = None,
) -> GhostJobAssessment:
    jd_score = await _score_jd(jd, session_id=session_id)

    signals: list[GhostSignal] = []
    for s in (
        _stale_signal(jd),
        _careers_page_signal(company_research),
        _vague_jd_signal(jd, jd_score),
        _distress_signal(companies_house),
    ):
        if s is not None:
            signals.append(s)

    probability, confidence = _combine(signals)

    age_days = (
        (date.today() - jd.posted_date).days if jd.posted_date else None
    )

    return GhostJobAssessment(
        probability=probability,
        signals=signals,
        confidence=confidence,
        raw_jd_score=jd_score,
        age_days=age_days,
    )
