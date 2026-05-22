"""Unit tests for the deterministic ghost-job JD scorer.

Tests the 5-dimension regex scoring in ghost_job_detector.py without
LLM calls. Verifies scoring thresholds, edge cases, and the bridge
from raw dimension scores to GhostJobJDScore.
"""

import pytest

from askpicky.schemas import (
    ExtractedJobDescription,
    GhostJobJDScore,
)


def _make_jd(text: str, *, hiring_manager_named: bool = False,
             required_skills: list | None = None,
             specificity_signals: list | None = None,
             vagueness_signals: list | None = None) -> ExtractedJobDescription:
    return ExtractedJobDescription(
        role_title="Software Engineer",
        seniority_signal="mid",
        soc_code_guess="2136",
        soc_guess_rationale="JD mentions software development",
        location="London",
        remote_policy="hybrid",
        required_skills=required_skills or [],
        posting_platform="company_site",
        hiring_manager_named=hiring_manager_named,
        jd_text_full=text,
        specificity_signals=specificity_signals or [],
        vagueness_signals=vagueness_signals or [],
    )


# ---------------------------------------------------------------------------
# Tech stack scoring
# ---------------------------------------------------------------------------

def test_tech_stack_score_empty_jd() -> None:
    from askpicky.sub_agents.ghost_job_detector import _score_tech_stack
    jd = _make_jd("We are looking for someone to join our team.")
    score, _signals = _score_tech_stack(jd)
    assert score == 0.0


def test_tech_stack_score_rich_jd() -> None:
    from askpicky.sub_agents.ghost_job_detector import _score_tech_stack
    jd = _make_jd(
        "Looking for a Python engineer. Must know TypeScript, React, "
        "Docker, Kubernetes, AWS, PostgreSQL, Redis, and GraphQL.",
        required_skills=["Python", "TypeScript", "React"],
    )
    score, signals = _score_tech_stack(jd)
    assert score == 1.0  # 8+ tokens
    assert len(signals) > 0


def test_tech_stack_score_moderate() -> None:
    from askpicky.sub_agents.ghost_job_detector import _score_tech_stack
    jd = _make_jd(
        "We use Python and PostgreSQL.",
        required_skills=["Python"],
    )
    score, _signals = _score_tech_stack(jd)
    assert score == 0.4  # 2 tokens (1 in text + 1 in skills)


# ---------------------------------------------------------------------------
# Duty bullet scoring
# ---------------------------------------------------------------------------

def test_duty_bullets_empty() -> None:
    from askpicky.sub_agents.ghost_job_detector import _score_duty_bullets
    jd = _make_jd("Join our great team. Be passionate about code.")
    score, count = _score_duty_bullets(jd)
    assert score == 0.0
    assert count == 0


def test_duty_bullets_action_verbs() -> None:
    from askpicky.sub_agents.ghost_job_detector import _score_duty_bullets
    jd = _make_jd(
        "Responsibilities:\n"
        "- Built the core data pipeline\n"
        "- Designed the API architecture\n"
        "- Shipped 3 major features\n"
        "- Reduced latency by 40%\n"
        "- Led a team of 4 engineers\n"
        "- Managed the migration to Kubernetes\n"
    )
    score, count = _score_duty_bullets(jd)
    assert score == 1.0  # 6+ bullets
    assert count >= 6


# ---------------------------------------------------------------------------
# Team context scoring
# ---------------------------------------------------------------------------

def test_team_context_none() -> None:
    from askpicky.sub_agents.ghost_job_detector import _score_team_context
    jd = _make_jd("Looking for a developer.")
    score, _signals = _score_team_context(jd)
    assert score == 0.0


def test_team_context_present() -> None:
    from askpicky.sub_agents.ghost_job_detector import _score_team_context
    jd = _make_jd(
        "You will report to the Head of Engineering and work alongside "
        "12 engineers in our platform team."
    )
    score, signals = _score_team_context(jd)
    assert score >= 0.5
    assert len(signals) > 0


# ---------------------------------------------------------------------------
# Success metrics scoring
# ---------------------------------------------------------------------------

def test_success_metrics_none() -> None:
    from askpicky.sub_agents.ghost_job_detector import _score_success_metrics
    jd = _make_jd("You will do good work.")
    score, _signals = _score_success_metrics(jd)
    assert score == 0.0


def test_success_metrics_present() -> None:
    from askpicky.sub_agents.ghost_job_detector import _score_success_metrics
    jd = _make_jd(
        "We serve 500,000 users and process $2M in transactions daily. "
        "Our p99 latency is under 50ms."
    )
    score, signals = _score_success_metrics(jd)
    assert score >= 0.5
    assert len(signals) > 0


# ---------------------------------------------------------------------------
# Full deterministic scorer
# ---------------------------------------------------------------------------

def test_full_deterministic_scorer() -> None:
    from askpicky.sub_agents.ghost_job_detector import _score_jd_deterministic
    jd = _make_jd(
        "Looking for a Python engineer. Must know TypeScript, React, "
        "Docker, Kubernetes, AWS, PostgreSQL, Redis, and GraphQL.\n\n"
        "Responsibilities:\n"
        "- Built the core data pipeline\n"
        "- Designed the API architecture\n"
        "- Shipped 3 major features\n"
        "- Reduced latency by 40%\n\n"
        "You will report to the Head of Engineering and work alongside "
        "12 engineers in our platform team.\n\n"
        "We serve 500,000 users and process $2M in transactions daily.",
        hiring_manager_named=False,
        required_skills=["Python", "TypeScript", "React"],
    )
    result = _score_jd_deterministic(jd)
    assert isinstance(result, GhostJobJDScore)
    assert result.specificity_score >= 3.0  # Very specific JD
    assert len(result.specificity_signals) > 0
    assert result.specific_tech_stack >= 0.7


def test_full_deterministic_scorer_vague() -> None:
    from askpicky.sub_agents.ghost_job_detector import _score_jd_deterministic
    jd = _make_jd(
        "Exciting opportunity at fast-growing startup. We're looking "
        "for a team player who can hit the ground running. Competitive "
        "salary and great benefits."
    )
    result = _score_jd_deterministic(jd)
    assert result.specificity_score <= 2.0  # Very vague JD
    assert len(result.vagueness_signals) > 0
