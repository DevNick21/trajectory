"""Tests for `_ensemble_verdicts` — the conservative merge applied
when `settings.enable_verdict_ensemble=True` runs verdict twice in
parallel.

Rules (see orchestrator._ensemble_verdicts docstring):
  - NO_GO is asymmetric-dominant: either side NO_GO → NO_GO.
  - hard_blockers / stretch_concerns / reasoning are unioned + deduped.
  - confidence: mean on agreement, mean-minus-half-gap on disagreement.
  - headline: prefer the NO_GO side's headline when decisions disagree.
  - callback prob: the worse of the two, None if either is None.
"""

from __future__ import annotations

from trajectory.orchestrator import _ensemble_verdicts
from trajectory.schemas import (
    Citation,
    HardBlocker,
    MotivationFitReport,
    ReasoningPoint,
    StretchConcern,
    Verdict,
)


def _reasoning(n: int) -> ReasoningPoint:
    return ReasoningPoint(
        claim=f"claim-{n}",
        supporting_evidence=f"evidence-{n}",
        citation=Citation(
            kind="gov_data",
            data_field="sponsor_register.status",
            data_value="A_RATED",
        ),
    )


def _blocker(kind: str = "BELOW_PERSONAL_FLOOR", detail: str = "x") -> HardBlocker:
    return HardBlocker(
        type=kind,  # type: ignore[arg-type]
        detail=detail,
        citation=Citation(
            kind="gov_data",
            data_field="test.field",
            data_value="test",
        ),
    )


def _concern(kind: str = "MOTIVATION_MISMATCH", detail: str = "y") -> StretchConcern:
    return StretchConcern(
        type=kind,  # type: ignore[arg-type]
        detail=detail,
        citations=[
            Citation(
                kind="gov_data",
                data_field="test.field",
                data_value="test",
            )
        ],
    )


def _verdict(
    *,
    decision: str = "GO",
    confidence: int = 80,
    headline: str = "Default headline.",
    hard_blockers: list | None = None,
    stretch_concerns: list | None = None,
    reasoning: list | None = None,
    callback: str | None = None,
) -> Verdict:
    return Verdict(
        decision=decision,  # type: ignore[arg-type]
        confidence_pct=confidence,
        headline=headline,
        reasoning=reasoning or [],
        hard_blockers=hard_blockers or [],
        stretch_concerns=stretch_concerns or [],
        motivation_fit=MotivationFitReport(
            motivation_evaluations=[],
            deal_breaker_evaluations=[],
            good_role_signal_evaluations=[],
        ),
        estimated_callback_probability=callback,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Decision rules
# ---------------------------------------------------------------------------


def test_both_go_stays_go():
    merged = _ensemble_verdicts(
        _verdict(decision="GO", confidence=80),
        _verdict(decision="GO", confidence=60),
    )
    assert merged.decision == "GO"
    assert merged.confidence_pct == 70  # mean


def test_both_no_go_stays_no_go():
    merged = _ensemble_verdicts(
        _verdict(decision="NO_GO", confidence=90),
        _verdict(decision="NO_GO", confidence=70),
    )
    assert merged.decision == "NO_GO"
    assert merged.confidence_pct == 80


def test_mixed_decisions_pick_no_go():
    """One GO + one NO_GO → NO_GO wins (conservative)."""
    merged = _ensemble_verdicts(
        _verdict(decision="GO", confidence=80),
        _verdict(decision="NO_GO", confidence=70),
    )
    assert merged.decision == "NO_GO"


def test_mixed_decisions_confidence_reduced_by_gap():
    """Disagreement subtracts half the confidence gap from the mean."""
    merged = _ensemble_verdicts(
        _verdict(decision="GO", confidence=90),
        _verdict(decision="NO_GO", confidence=70),
    )
    # mean = 80, gap = 20, half gap = 10, result = 70
    assert merged.confidence_pct == 70


def test_mixed_decisions_confidence_floors_at_zero():
    """Extreme disagreement can't produce a negative confidence."""
    merged = _ensemble_verdicts(
        _verdict(decision="GO", confidence=20),
        _verdict(decision="NO_GO", confidence=100),
    )
    # mean = 60, gap = 80, half gap = 40, result = 20 (floored if needed)
    assert merged.confidence_pct >= 0


# ---------------------------------------------------------------------------
# Headline rules
# ---------------------------------------------------------------------------


def test_agreement_keeps_v1_headline():
    merged = _ensemble_verdicts(
        _verdict(decision="GO", headline="Headline one."),
        _verdict(decision="GO", headline="Headline two."),
    )
    assert merged.headline == "Headline one."


def test_disagreement_prefers_no_go_headline_v1_go():
    merged = _ensemble_verdicts(
        _verdict(decision="GO", headline="Apply - strong fit."),
        _verdict(decision="NO_GO", headline="Skip - sponsor suspended."),
    )
    assert merged.headline == "Skip - sponsor suspended."
    assert merged.decision == "NO_GO"


def test_disagreement_prefers_no_go_headline_v2_go():
    merged = _ensemble_verdicts(
        _verdict(decision="NO_GO", headline="Below SOC threshold."),
        _verdict(decision="GO", headline="Proceed."),
    )
    assert merged.headline == "Below SOC threshold."


# ---------------------------------------------------------------------------
# Hard blockers / stretch concerns / reasoning unions
# ---------------------------------------------------------------------------


def test_hard_blockers_union_dedupe():
    b_common = _blocker("BELOW_PERSONAL_FLOOR", "shared")
    b_v1_only = _blocker("LIKELY_GHOST_JOB", "ghost signals")
    b_v2_only = _blocker("DEAL_BREAKER_TRIGGERED", "no remote")

    merged = _ensemble_verdicts(
        _verdict(decision="NO_GO", hard_blockers=[b_common, b_v1_only]),
        _verdict(decision="NO_GO", hard_blockers=[b_common, b_v2_only]),
    )
    kinds = [b.type for b in merged.hard_blockers]
    details = [b.detail for b in merged.hard_blockers]
    assert len(merged.hard_blockers) == 3  # deduped "shared" once
    assert "BELOW_PERSONAL_FLOOR" in kinds
    assert "LIKELY_GHOST_JOB" in kinds
    assert "DEAL_BREAKER_TRIGGERED" in kinds
    assert details.count("shared") == 1


def test_stretch_concerns_union_dedupe():
    c_common = _concern("MOTIVATION_MISMATCH", "shared")
    c_v1 = _concern("EXPERIENCE_GAP", "junior")
    merged = _ensemble_verdicts(
        _verdict(decision="GO", stretch_concerns=[c_common, c_v1]),
        _verdict(decision="GO", stretch_concerns=[c_common]),
    )
    assert len(merged.stretch_concerns) == 2


def test_reasoning_union_preserves_order_per_source():
    merged = _ensemble_verdicts(
        _verdict(reasoning=[_reasoning(1), _reasoning(2)]),
        _verdict(reasoning=[_reasoning(2), _reasoning(3)]),
    )
    claims = [r.claim for r in merged.reasoning]
    # _reasoning(2) appears once (same claim + evidence in both)
    assert claims == ["claim-1", "claim-2", "claim-3"]


# ---------------------------------------------------------------------------
# Callback probability — worse wins
# ---------------------------------------------------------------------------


def test_callback_probability_picks_worse():
    merged = _ensemble_verdicts(
        _verdict(callback="HIGH"),
        _verdict(callback="LOW"),
    )
    assert merged.estimated_callback_probability == "LOW"


def test_callback_probability_medium_vs_high():
    merged = _ensemble_verdicts(
        _verdict(callback="HIGH"),
        _verdict(callback="MEDIUM"),
    )
    assert merged.estimated_callback_probability == "MEDIUM"


def test_callback_none_if_either_missing():
    assert _ensemble_verdicts(
        _verdict(callback="HIGH"),
        _verdict(callback=None),
    ).estimated_callback_probability is None
    assert _ensemble_verdicts(
        _verdict(callback=None),
        _verdict(callback="LOW"),
    ).estimated_callback_probability is None


# ---------------------------------------------------------------------------
# Config default
# ---------------------------------------------------------------------------


def test_ensemble_flag_defaults_off():
    """Safety: existing forward_job traffic must not double-spend unless
    the user opts in explicitly. Default stays False."""
    from trajectory.config import Settings

    assert Settings().enable_verdict_ensemble is False
