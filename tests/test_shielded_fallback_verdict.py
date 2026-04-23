"""Test the Content Shield REJECT → fallback verdict path.

Per AGENTS.md §18, when Tier 2 returns recommended_action=REJECT for a
forward_job run, the orchestrator must produce a minimal NO_GO verdict
with CONTENT_INTEGRITY_CONCERN as a stretch concern — not bail, not
ship an agent-generated verdict against shielded input.

This test exercises `_build_shielded_fallback_verdict` directly so the
shape doesn't drift without being caught.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from trajectory.orchestrator import _build_shielded_fallback_verdict
from trajectory.schemas import (
    ContentShieldVerdict,
    ResearchBundle,
)


def _load_bundle() -> ResearchBundle:
    fixture = Path(__file__).parent / "fixtures" / "sample_research_bundle.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    # The fixture was generated against an older schema — backfill the
    # fields this test requires with sensible defaults.
    data.setdefault(
        "bundle_completed_at",
        datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    )
    return ResearchBundle.model_validate(data)


def test_fallback_verdict_is_no_go_with_content_integrity_concern() -> None:
    bundle = _load_bundle()
    shield_verdict = ContentShieldVerdict(
        classification="MALICIOUS",
        reasoning="embedded instruction tries to flip the verdict to GO",
        residual_patterns_detected=["ignore_previous"],
        recommended_action="REJECT",
    )

    verdict = _build_shielded_fallback_verdict(bundle, shield_verdict)

    assert verdict.decision == "NO_GO"
    assert verdict.hard_blockers == []
    assert len(verdict.stretch_concerns) == 1
    assert verdict.stretch_concerns[0].type == "CONTENT_INTEGRITY_CONCERN"
    assert len(verdict.reasoning) >= 1
    assert verdict.confidence_pct <= 50
    # Every reasoning point carries a resolvable citation so the
    # verdict still passes the standard validator shape.
    for r in verdict.reasoning:
        assert r.citation is not None


def test_fallback_verdict_headline_is_under_12_words() -> None:
    bundle = _load_bundle()
    shield_verdict = ContentShieldVerdict(
        classification="SUSPICIOUS",
        reasoning="x",
        residual_patterns_detected=[],
        recommended_action="REJECT",
    )
    verdict = _build_shielded_fallback_verdict(bundle, shield_verdict)
    assert len(verdict.headline.split()) <= 12
