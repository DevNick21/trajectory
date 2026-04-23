"""Tests for the LaTeX template choice heuristic."""

from __future__ import annotations

from typing import Optional

from trajectory.renderers.cv_latex import _choose_latex_template
from trajectory.schemas import CVOutput


def _cv() -> CVOutput:
    return CVOutput(
        name="X",
        contact={},
        professional_summary="x",
        experience=[],
        education=[],
        skills=[],
    )


def _check(target_role: Optional[str], expected: str) -> None:
    assert _choose_latex_template(_cv(), target_role) == expected, target_role


def test_none_target_picks_modern():
    _check(None, "modern_one_column")


def test_empty_target_picks_modern():
    _check("", "modern_one_column")


def test_finance_keywords_pick_traditional():
    for role in [
        "Investment Analyst",
        "Compliance Officer",
        "Senior Auditor",
        "Insurance Associate",
        "Actuarial Consultant",
        "Banking Analyst",
        "Regulatory Reporting Lead",
        "Legal Counsel",
        "Corporate Finance Manager",
    ]:
        _check(role, "traditional_two_column")


def test_tech_roles_pick_modern():
    for role in [
        "Senior Backend Engineer",
        "Staff SRE",
        "Platform Engineer",
        "Machine Learning Engineer",
        "Product Engineer",
        "Civil Service Software Developer",
    ]:
        _check(role, "modern_one_column")


def test_mixed_case_match():
    _check("INVESTMENT BANKING ASSOCIATE", "traditional_two_column")
    _check("senior PYTHON developer", "modern_one_column")


def test_substring_match_in_compound_titles():
    # "Compliance" buried in a larger title still triggers.
    _check("Head of Risk and Compliance", "traditional_two_column")
