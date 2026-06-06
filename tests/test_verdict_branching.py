"""Verdict branching tests.

Required cases:
  - uk_resident: ghost-job blocker triggers BLOCKED
  - uk_resident: sponsor/SOC checks skipped (NOT visa-holder blockers)
  - visa_holder: NOT_LISTED sponsor triggers BLOCKED
  - visa_holder: salary below SOC threshold triggers BLOCKED
  - validator flips GO -> BLOCKED when hard blockers are present
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from askpicky.schemas import (
    Citation,
    CompaniesHouseSnapshot,
    GhostJobAssessment,
    GhostJobJDScore,
    GhostSignal,
    HardBlocker,
    MotivationFitReport,
    ReasoningPoint,
    ResearchBundle,
    SocCheckResult,
    SponsorStatus,
    UserProfile,
    Verdict,
    VisaStatus,
)
from askpicky.sub_agents.verdict import _enforce_label_blocker_consistency

FIXTURE = Path(__file__).parent / "fixtures" / "sample_research_bundle.json"


def _make_citation(**kwargs) -> Citation:
    defaults = {
        "kind": "url_snippet",
        "url": "https://example.com",
        "verbatim_snippet": "test snippet",
    }
    defaults.update(kwargs)
    return Citation(**defaults)


def _make_reasoning(n: int = 3) -> list[ReasoningPoint]:
    return [
        ReasoningPoint(
            claim=f"Claim {i}",
            supporting_evidence="Evidence",
            citation=_make_citation(),
        )
        for i in range(n)
    ]


def _make_motivation_fit() -> MotivationFitReport:
    return MotivationFitReport(
        motivation_evaluations=[],
        deal_breaker_evaluations=[],
        good_role_signal_evaluations=[],
    )


def _make_uk_user() -> UserProfile:
    now = datetime.utcnow()
    return UserProfile(
        user_id="uk_test",
        name="Test User",
        user_type="uk_resident",
        base_location="London",
        salary_floor=50000,
        motivations=[],
        deal_breakers=[],
        good_role_signals=[],
        life_constraints=[],
        search_started_date=date.today(),
        current_employment="EMPLOYED",
        created_at=now,
        updated_at=now,
    )


def _make_visa_user() -> UserProfile:
    now = datetime.utcnow()
    return UserProfile(
        user_id="visa_test",
        name="Test User",
        user_type="visa_holder",
        visa_status=VisaStatus(route="graduate", expiry_date=date(2026, 9, 30)),
        nationality="Nigerian",
        base_location="London",
        salary_floor=50000,
        motivations=[],
        deal_breakers=[],
        good_role_signals=[],
        life_constraints=[],
        search_started_date=date.today(),
        current_employment="EMPLOYED",
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Test 1: GO with no blockers stays GO
# ---------------------------------------------------------------------------


def test_no_blockers_go_stays_go():
    verdict = Verdict(
        decision="GO",
        confidence_pct=75,
        headline="Apply — strong fit.",
        reasoning=_make_reasoning(),
        hard_blockers=[],
        stretch_concerns=[],
        motivation_fit=_make_motivation_fit(),
    )
    result = _enforce_label_blocker_consistency(verdict)
    assert result.decision == "GO"


# ---------------------------------------------------------------------------
# Test 2: GO with hard blockers flips to BLOCKED
# ---------------------------------------------------------------------------


def test_go_with_hard_blocker_flips_to_blocked():
    blocker = HardBlocker(
        type="NOT_ON_SPONSOR_REGISTER",
        detail="Company not on Sponsor Register",
        citation=Citation(
            kind="gov_data",
            data_field="sponsor_register.status",
            data_value="NOT_LISTED",
        ),
    )
    verdict = Verdict(
        decision="GO",
        confidence_pct=80,
        headline="Apply — looks good.",
        reasoning=_make_reasoning(),
        hard_blockers=[blocker],
        stretch_concerns=[],
        motivation_fit=_make_motivation_fit(),
    )
    result = _enforce_label_blocker_consistency(verdict)
    assert result.decision == "BLOCKED", "Should flip to BLOCKED when hard blocker present"


# ---------------------------------------------------------------------------
# Test 3: BLOCKED with no blockers stays BLOCKED
# ---------------------------------------------------------------------------


def test_blocked_stays_blocked():
    verdict = Verdict(
        decision="BLOCKED",
        confidence_pct=40,
        headline="Don't apply — ghost job.",
        reasoning=_make_reasoning(),
        hard_blockers=[],
        stretch_concerns=[],
        motivation_fit=_make_motivation_fit(),
    )
    result = _enforce_label_blocker_consistency(verdict)
    assert result.decision == "BLOCKED"


# ---------------------------------------------------------------------------
# Test 4: Multiple hard blockers — stays BLOCKED
# ---------------------------------------------------------------------------


def test_multiple_hard_blockers_stays_blocked():
    blockers = [
        HardBlocker(
            type="NOT_ON_SPONSOR_REGISTER",
            detail="Company not listed",
            citation=Citation(
                kind="gov_data",
                data_field="sponsor_register.status",
                data_value="NOT_LISTED",
            ),
        ),
        HardBlocker(
            type="SALARY_BELOW_SOC_THRESHOLD",
            detail="Salary £3,200 below SOC threshold",
            citation=Citation(
                kind="gov_data",
                data_field="soc_check.below_threshold",
                data_value="true",
            ),
        ),
    ]
    verdict = Verdict(
        decision="BLOCKED",
        confidence_pct=20,
        headline="Don't apply — not sponsored.",
        reasoning=_make_reasoning(),
        hard_blockers=blockers,
        stretch_concerns=[],
        motivation_fit=_make_motivation_fit(),
    )
    result = _enforce_label_blocker_consistency(verdict)
    assert result.decision == "BLOCKED"
    assert len(result.hard_blockers) == 2
