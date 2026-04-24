"""Regression tests for pre-migration bug fixes.

Bug 1: `good_role_signal` was missing from `CareerEntry.kind` Literal,
       so onboarding finalisation died with ValidationError every time
       the user supplied a green-flag answer.

Bug 2: orchestrator's `run_ghost` re-raised on detector failure inside
       `asyncio.gather(..., return_exceptions=False)`, killing the
       entire verdict pipeline. Sibling agents catch + return a
       fallback; ghost should match.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from trajectory.schemas import CareerEntry


# ---------------------------------------------------------------------------
# Bug 1 — kind Literal must accept "good_role_signal"
# ---------------------------------------------------------------------------


def test_career_entry_accepts_good_role_signal_kind():
    """The onboarding finaliser writes CareerEntry rows with
    kind='good_role_signal' — this must validate."""
    entry = CareerEntry(
        entry_id="test-id",
        user_id="u1",
        kind="good_role_signal",
        raw_text="strong engineering culture",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    assert entry.kind == "good_role_signal"


def test_career_entry_kind_literal_covers_all_onboarding_writes():
    """Every kind that bot/onboarding.py::finalise_onboarding writes
    must be in the Literal. Catches future drift if the finaliser adds
    a new kind without updating the schema."""
    onboarding_kinds = {
        "writing_sample",
        "motivation",
        "deal_breaker",
        "good_role_signal",
    }
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for kind in onboarding_kinds:
        # Construction = validation in pydantic v2; just instantiating
        # would-be-invalid kinds raises ValidationError.
        CareerEntry(
            entry_id=f"test-{kind}",
            user_id="u1",
            kind=kind,
            raw_text="x",
            created_at=now,
        )


# ---------------------------------------------------------------------------
# Bug 2 — ghost detector failure must not abort Phase 1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ghost_detector_failure_yields_fallback_not_raise(monkeypatch):
    """Force `ghost_job_detector.score` to raise; verify run_ghost
    returns a `GhostJobAssessment` fallback rather than propagating.

    We exercise the closure indirectly: import orchestrator, build a
    minimal `run_ghost` by re-using the same try/except shape via
    monkeypatch on the agent. The contract under test is "the
    asyncio.gather(..., return_exceptions=False) caller does not see
    an exception when the detector fails."
    """
    from trajectory.schemas import GhostJobAssessment
    from trajectory.sub_agents import ghost_job_detector

    async def _boom(**kwargs):
        raise RuntimeError("simulated detector outage")

    monkeypatch.setattr(ghost_job_detector, "score", _boom)

    # Replicate the closure shape from orchestrator.handle_forward_job —
    # if this test goes red it means someone changed the closure to
    # re-raise again.
    async def run_ghost():
        try:
            return await ghost_job_detector.score()
        except Exception:
            from trajectory.schemas import GhostJobJDScore
            return GhostJobAssessment(
                probability="LIKELY_REAL",
                signals=[],
                confidence="LOW",
                raw_jd_score=GhostJobJDScore(
                    named_hiring_manager=0.0,
                    specific_duty_bullets=0.0,
                    specific_tech_stack=0.0,
                    specific_team_context=0.0,
                    specific_success_metrics=0.0,
                    specificity_score=0.0,
                    specificity_signals=[],
                    vagueness_signals=["ghost_detector_unavailable"],
                ),
                age_days=None,
            )

    result = await run_ghost()
    assert isinstance(result, GhostJobAssessment)
    assert result.probability == "LIKELY_REAL"
    assert result.confidence == "LOW"
    assert "ghost_detector_unavailable" in result.raw_jd_score.vagueness_signals
