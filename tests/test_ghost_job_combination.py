"""Ghost-job signal combination tests.

Required cases from CLAUDE.md:
  - 2+ HARD → LIKELY_GHOST HIGH
  - 1 HARD + 1 SOFT → LIKELY_GHOST MEDIUM
  - 1 HARD alone → POSSIBLE_GHOST MEDIUM
  - 0 HARD + 2 SOFT → POSSIBLE_GHOST MEDIUM
  - 0 HARD + 1 SOFT → POSSIBLE_GHOST LOW
  - 0 → LIKELY_REAL HIGH
"""

from __future__ import annotations

import pytest

from trajectory.sub_agents.ghost_job_detector import _combine
from trajectory.schemas import Citation, GhostSignal


def _sig(severity: str, sig_type: str = "STALE_POSTING") -> GhostSignal:
    return GhostSignal(
        type=sig_type,
        evidence="test evidence",
        citation=Citation(
            kind="url_snippet",
            url="https://example.com",
            verbatim_snippet="test",
        ),
        severity=severity,
    )


def test_two_hard_signals_likely_ghost_high():
    """2 HARD signals → LIKELY_GHOST with HIGH confidence."""
    signals = [
        _sig("HARD", "NOT_ON_CAREERS_PAGE"),
        _sig("HARD", "STALE_POSTING"),
    ]
    probability, confidence = _combine(signals)
    assert probability == "LIKELY_GHOST"
    assert confidence == "HIGH"


def test_one_hard_one_soft_likely_ghost_medium():
    """1 HARD + 1 SOFT → LIKELY_GHOST with MEDIUM confidence."""
    signals = [
        _sig("HARD", "NOT_ON_CAREERS_PAGE"),
        _sig("SOFT", "STALE_POSTING"),
    ]
    probability, confidence = _combine(signals)
    assert probability == "LIKELY_GHOST"
    assert confidence == "MEDIUM"


def test_one_hard_alone_possible_ghost_medium():
    """1 HARD signal alone → POSSIBLE_GHOST with MEDIUM confidence."""
    signals = [_sig("HARD", "VAGUE_JD")]
    probability, confidence = _combine(signals)
    assert probability == "POSSIBLE_GHOST"
    assert confidence == "MEDIUM"


def test_two_soft_possible_ghost_medium():
    """0 HARD + 2 SOFT → POSSIBLE_GHOST with MEDIUM confidence."""
    signals = [
        _sig("SOFT", "STALE_POSTING"),
        _sig("SOFT", "VAGUE_JD"),
    ]
    probability, confidence = _combine(signals)
    assert probability == "POSSIBLE_GHOST"
    assert confidence == "MEDIUM"


def test_one_soft_possible_ghost_low():
    """0 HARD + 1 SOFT → POSSIBLE_GHOST with LOW confidence."""
    signals = [_sig("SOFT", "STALE_POSTING")]
    probability, confidence = _combine(signals)
    assert probability == "POSSIBLE_GHOST"
    assert confidence == "LOW"


def test_no_signals_likely_real_high():
    """No signals → LIKELY_REAL with HIGH confidence."""
    probability, confidence = _combine([])
    assert probability == "LIKELY_REAL"
    assert confidence == "HIGH"
