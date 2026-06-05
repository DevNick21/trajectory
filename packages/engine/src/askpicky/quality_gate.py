"""Quality gate — deterministic pre-verdict reduction pass.

Runs between Phase 1 (research) and Phase 2 (verdict). Takes the raw
ResearchBundle and produces a QualityGatedBundle that declares which
signals are reliable and which hard-blocker rules can actually fire.

This is the same pattern social media realtime systems use: a firehose
filter (deterministic, fast, handles 99% of quality decisions) before the
ranking model (expensive, only sees clean data). The verdict currently
does both jobs — it has to evaluate data quality AND make a GO/NO_GO
decision in a single call. That's why verdicts are inconsistent.

No LLM. No API calls. Runs in <1ms. Pure functions, testable in isolation.
"""

from __future__ import annotations

import logging
from typing import Optional

from .schemas import (
    CompaniesHouseSnapshot,
    CompanyResearch,
    ExtractedJobDescription,
    GhostJobAssessment,
    GhostSignal,
    ResearchBundle,
    SocCheckResult,
    SponsorStatus,
    UserProfile,
)

logger = logging.getLogger(__name__)


class QualityGatedBundle:
    """The verdict receives this alongside the raw ResearchBundle.

    Keys are the Phase 1 signal group names. Values declare whether
    the group's hard-blocker rules can fire. When a group is gated
    (downgraded), the verdict treats all its signals as advisory.
    """

    def __init__(self) -> None:
        self.gated: dict[str, str] = {}       # signal_group → reason
        self.upgrades: dict[str, str] = {}     # signal_group → "elevated from X to Y"
        self.notes: list[str] = []             # informational

    def gate(self, group: str, reason: str) -> None:
        self.gated[group] = reason

    def upgrade(self, group: str, reason: str) -> None:
        self.upgrades[group] = reason

    def note(self, text: str) -> None:
        self.notes.append(text)

    def to_user_input(self) -> dict:
        return {
            "gated_signals": self.gated,
            "upgraded_signals": self.upgrades,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Individual quality checks — one function per Phase 1 input
# ---------------------------------------------------------------------------


def _check_jd_fetch(jd: ExtractedJobDescription) -> Optional[str]:
    """Returns a reason string if the JD wasn't properly fetched."""
    text = (jd.jd_text_full or "").strip()
    role = (jd.role_title or "").strip()
    if not text or len(text) < 100:
        return f"JD text not retrieved ({len(text)} chars). Role title: '{role or 'UNKNOWN'}'. Likely a session-walled ATS (Oracle HCM, Workday, Greenhouse)."
    if role in {"<UNKNOWN>", "Unknown"} and not jd.required_skills:
        return f"JD parsed but no role title or skills extracted. Raw text length: {len(text)}."
    return None


def _check_entity_resolution(
    companies_house: Optional[CompaniesHouseSnapshot],
    sponsor_status: Optional[SponsorStatus],
    company_research: CompanyResearch,
) -> list[str]:
    """Returns reasons why entity resolution should be downgraded."""
    reasons: list[str] = []

    if companies_house and companies_house.match_confidence < 0.5:
        reasons.append(
            f"Companies House match confidence is {companies_house.match_confidence:.2f} "
            f"(match_path={companies_house.match_path}). "
            f"Matched entity: {companies_house.company_name_official} "
            f"(CRN {companies_house.company_number}, status={companies_house.status}). "
            f"The resolver may have anchored on the wrong legal entity — "
            f"treat CH status, dissolution, and filing signals as advisory only."
        )

    if companies_house and companies_house.match_confidence < 0.9:
        reasons.append(
            f"Companies House match is fuzzy (confidence {companies_house.match_confidence:.2f}, "
            f"path={companies_house.match_path}). "
            f"The canonical company name in the JD ({company_research.company_name}) "
            f"may not match the CH legal name ({companies_house.company_name_official})."
        )

    # Shell detection: dissolved + incorporated recently = wrong entity
    if companies_house and companies_house.status in {"DISSOLVED", "IN_ADMINISTRATION", "IN_LIQUIDATION"}:
        if companies_house.match_confidence < 0.7:
            reasons.append(
                f"Matched entity is {companies_house.status} with low resolver confidence "
                f"({companies_house.match_confidence:.2f}) — this is likely the wrong entity. "
                f"The real employer may operate under a different CH entity."
            )

    if sponsor_status and sponsor_status.match_confidence < 0.9:
        reasons.append(
            f"Sponsor Register match confidence is {sponsor_status.match_confidence:.2f} "
            f"(path={sponsor_status.match_path}). "
            f"If status is NOT_LISTED, treat as AMBIGUOUS — the company may be on the "
            f"register under a different legal name."
        )

    if sponsor_status and sponsor_status.register_age_days and sponsor_status.register_age_days >= 7:
        reasons.append(
            f"Sponsor Register parquet is {sponsor_status.register_age_days} days old "
            f"(updated daily by the Home Office). A NOT_LISTED result may be stale — "
            f"a licence granted in the last week won't appear."
        )

    return reasons


def _check_ghost_signals(
    ghost: GhostJobAssessment,
    jd: ExtractedJobDescription,
    companies_house: Optional[CompaniesHouseSnapshot],
) -> list[str]:
    """Returns reasons to downgrade ghost-job signals."""
    reasons: list[str] = []

    # When the JD wasn't fetched, all ghost signals are artefacts of missing data
    jd_missing = _check_jd_fetch(jd) is not None
    if jd_missing:
        reasons.append(
            "JD not properly fetched — all ghost-job signals are SOFT. "
            "VAGUE_JD and NOT_ON_CAREERS_PAGE cannot be meaningfully evaluated "
            "without the actual job description text."
        )

    # When the DISTRESS signal comes from a low-confidence CH match
    has_distress = any(s.type == "COMPANY_DISTRESS" for s in ghost.signals)
    if has_distress and companies_house and companies_house.match_confidence < 0.5:
        reasons.append(
            f"Ghost DISTRESS signal is based on a low-confidence Companies House match "
            f"(confidence={companies_house.match_confidence:.2f}). "
            f"The dissolution/distress may not apply to the real employer."
        )

    # When ghost is LIKELY_GHOST but all signals trace to a single root cause
    if ghost.probability == "LIKELY_GHOST" and ghost.confidence == "HIGH":
        unique_types = {s.type for s in ghost.signals}
        if len(unique_types) <= 1 or jd_missing:
            reasons.append(
                f"Ghost probability is {ghost.probability} at {ghost.confidence} confidence "
                f"but all {len(ghost.signals)} signal(s) trace to a single root cause "
                f"({' / '.join(unique_types)}). "
                f"This is a LOW-confidence LIKELY_GHOST, not a hard blocker."
            )

    return reasons


def _check_soc_data(
    soc: Optional[SocCheckResult],
) -> list[str]:
    """Returns reasons to downgrade SOC/going-rate signals."""
    reasons: list[str] = []

    if soc is None:
        reasons.append("SOC check returned no data — salary threshold cannot be evaluated.")
        return reasons

    if soc.source_status in {"NO_DATA", "STALE", "UNREACHABLE"}:
        reasons.append(
            f"SOC check source status is {soc.source_status}. "
            f"Cannot evaluate salary-vs-going-rate threshold."
        )

    if soc.match_confidence < 0.7:
        reasons.append(
            f"SOC code assignment confidence is {soc.match_confidence:.2f} "
            f"(guessed code: {soc.soc_code}). The salary threshold may apply "
            f"to the wrong occupation."
        )

    if soc.offered_salary_gbp is None:
        reasons.append(
            "No salary posted in the JD — cannot compare against SOC going rate "
            "or user's personal floor."
        )

    return reasons


def _check_sponsor_status(
    sponsor: Optional[SponsorStatus],
    user: UserProfile,
) -> list[str]:
    """Returns reasons to gate sponsor-related hard blockers."""
    reasons: list[str] = []

    if sponsor is None:
        if user.user_type == "visa_holder":
            reasons.append("Sponsor Register lookup failed entirely — cannot evaluate sponsorship.")
        return reasons

    # NOT_LISTED with low confidence → not a hard blocker
    if sponsor.status == "NOT_LISTED" and sponsor.match_confidence < 0.95:
        reasons.append(
            f"Sponsor status is NOT_LISTED but match confidence is only "
            f"{sponsor.match_confidence:.2f} (path={sponsor.match_path}). "
            f"Treat as AMBIGUOUS — the employer may be on the register under "
            f"a different legal entity. Verify directly on gov.uk."
        )

    if sponsor.status == "NOT_LISTED" and sponsor.alternative_matches:
        alt_names = [m.matched_name for m in sponsor.alternative_matches[:3]]
        reasons.append(
            f"Sponsor Register has {len(sponsor.alternative_matches)} near-matches "
            f"({', '.join(alt_names)}). The employer may use one of these names "
            f"on the register."
        )

    # Stale data
    if sponsor.register_age_days and sponsor.register_age_days >= 7:
        reasons.append(
            f"Sponsor Register snapshot is {sponsor.register_age_days} days old. "
            f"A licence granted in the last week won't appear."
        )

    # B_RATED or SUSPENDED are still meaningful — they're on the register
    # but with restrictions. Don't gate these.

    return reasons


# ---------------------------------------------------------------------------
# Top-level gate — called before every verdict
# ---------------------------------------------------------------------------


def assess(
    bundle: ResearchBundle,
    user: UserProfile,
) -> QualityGatedBundle:
    """Run all quality checks against the research bundle. Returns a gate
    the verdict agent can reason over.

    Gated groups → verdict treats their signals as advisory (stretch
    concerns, not hard blockers). Ungated groups → verdict can fire
    their hard-blocker rules normally.
    """
    gate = QualityGatedBundle()
    jd = bundle.extracted_jd
    ch = bundle.companies_house
    sponsor = bundle.sponsor_status
    soc = bundle.soc_check
    ghost = bundle.ghost_job
    cr = bundle.company_research

    # ── JD fetch quality ────────────────────────────────────────────────
    jd_fetch_reason = _check_jd_fetch(jd)
    if jd_fetch_reason:
        gate.gate("ghost_job_vague_jd", jd_fetch_reason)
        gate.gate("motivation_fit", "Cannot evaluate motivation fit without JD content")
        gate.gate("deal_breaker_check", "Cannot check deal-breakers against absent JD")
        gate.gate("soc_check", "SOC code cannot be assigned without JD duties")
        gate.note(jd_fetch_reason)
    else:
        gate.upgrade("jd_fetch", "JD text successfully retrieved and parsed")

    # ── Entity resolution quality ───────────────────────────────────────
    entity_reasons = _check_entity_resolution(ch, sponsor, cr)
    for reason in entity_reasons:
        gate.note(reason)
    if ch and ch.match_confidence < 0.5:
        gate.gate("companies_house", entity_reasons[0] if entity_reasons else "Low entity resolution confidence")
    if sponsor and sponsor.match_confidence < 0.9:
        gate.gate("sponsor_register", "Low match confidence — status may not apply to this employer")

    # ── Ghost-job signal quality ────────────────────────────────────────
    ghost_reasons = _check_ghost_signals(ghost, jd, ch)
    for reason in ghost_reasons:
        gate.note(reason)
    if jd_fetch_reason:
        gate.gate("ghost_job", "JD not fetched — ghost signals are artefacts of missing data")
    elif ghost.probability == "LIKELY_GHOST" and len({s.type for s in ghost.signals}) <= 1:
        gate.gate("ghost_job", "LIKELY_GHOST from single signal type — may be a false positive")

    # ── SOC / salary threshold quality ──────────────────────────────────
    soc_reasons = _check_soc_data(soc)
    for reason in soc_reasons:
        gate.note(reason)
    if soc_reasons:
        gate.gate("soc_threshold", "; ".join(soc_reasons))

    # ── Sponsor Register quality ────────────────────────────────────────
    sponsor_reasons = _check_sponsor_status(sponsor, user)
    for reason in sponsor_reasons:
        gate.note(reason)
    if sponsor_reasons and user.user_type == "visa_holder":
        gate.gate("sponsor_hard_blocker", "; ".join(sponsor_reasons))

    logger.info(
        "Quality gate: %d gated, %d upgraded, %d notes for session %s",
        len(gate.gated), len(gate.upgrades), len(gate.notes),
        bundle.session_id,
    )

    return gate
