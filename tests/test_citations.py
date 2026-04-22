"""Citation validator tests.

4 required cases: whitespace tolerance, URL mismatch, gov field, career entry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trajectory.schemas import (
    CareerEntry,
    Citation,
    ResearchBundle,
    Verdict,
    ReasoningPoint,
    MotivationFitReport,
    HardBlocker,
)
from trajectory.validators.citations import (
    ValidationContext,
    validate_citation,
    validate_output,
    build_context,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_research_bundle.json"


@pytest.fixture
def bundle() -> ResearchBundle:
    with open(FIXTURE) as f:
        return ResearchBundle.model_validate(json.load(f))


@pytest.fixture
def ctx(bundle: ResearchBundle) -> ValidationContext:
    return ValidationContext(research_bundle=bundle, career_store_entries={})


# ---------------------------------------------------------------------------
# 1. Whitespace-normalised snippet matching
# ---------------------------------------------------------------------------


def test_url_snippet_whitespace_tolerance(ctx: ValidationContext):
    """Verbatim snippets with leading/trailing whitespace still validate."""
    citation = Citation(
        kind="url_snippet",
        url="https://acmetech.io/careers",
        verbatim_snippet="  Our engineering team ships autonomously.  ",
    )
    ok, reason = validate_citation(citation, ctx)
    assert ok, f"Expected ok but got: {reason}"


# ---------------------------------------------------------------------------
# 2. URL mismatch — should fail
# ---------------------------------------------------------------------------


def test_url_snippet_wrong_url_fails(ctx: ValidationContext):
    """A snippet from a page that was never scraped must fail."""
    citation = Citation(
        kind="url_snippet",
        url="https://not-scraped.io/careers",
        verbatim_snippet="Our engineering team ships autonomously.",
    )
    ok, reason = validate_citation(citation, ctx)
    assert not ok, "Expected validation failure for unscraped URL"


# ---------------------------------------------------------------------------
# 3. Gov data field resolution
# ---------------------------------------------------------------------------


def test_gov_data_sponsor_register_listed(ctx: ValidationContext):
    """sponsor_register.status = LISTED should resolve correctly."""
    citation = Citation(
        kind="gov_data",
        data_field="sponsor_register.status",
        data_value="LISTED",
    )
    ok, reason = validate_citation(citation, ctx)
    assert ok, f"Expected ok but got: {reason}"


def test_gov_data_wrong_value_fails(ctx: ValidationContext):
    """sponsor_register.status claiming NOT_LISTED when bundle says LISTED must fail."""
    citation = Citation(
        kind="gov_data",
        data_field="sponsor_register.status",
        data_value="NOT_LISTED",
    )
    ok, reason = validate_citation(citation, ctx)
    assert not ok, "Expected validation failure for wrong gov data value"


# ---------------------------------------------------------------------------
# 4. Career entry existence check
# ---------------------------------------------------------------------------


def test_career_entry_exists():
    """A career entry that exists in the store should validate."""
    from datetime import datetime

    entry = CareerEntry(
        entry_id="entry-abc-123",
        user_id="user1",
        kind="cv_bullet",
        raw_text="Built a thing",
        created_at=datetime.utcnow(),
    )
    ctx = ValidationContext(
        research_bundle=None,
        career_store_entries={"entry-abc-123": entry},
    )
    citation = Citation(kind="career_entry", entry_id="entry-abc-123")
    ok, reason = validate_citation(citation, ctx)
    assert ok, f"Expected ok but got: {reason}"


def test_career_entry_missing_fails():
    """A career entry that doesn't exist must fail."""
    ctx = ValidationContext(research_bundle=None, career_store_entries={})
    citation = Citation(kind="career_entry", entry_id="nonexistent-entry-999")
    ok, reason = validate_citation(citation, ctx)
    assert not ok, "Expected validation failure for missing career entry"
