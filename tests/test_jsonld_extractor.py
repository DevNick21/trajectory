"""Tests for src/trajectory/sub_agents/jsonld_extractor.py.

Hardcoded representative JSON-LD fixtures per known-good ATS site.
Tests are deterministic and offline — never hit the network.
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

import pytest

from trajectory.schemas import JsonLdExtraction
from trajectory.sub_agents.jsonld_extractor import extract_jsonld_jobposting


def _wrap(jsonld_obj: dict | list) -> str:
    """Wrap a JSON-LD payload into a minimal HTML document."""
    return (
        "<html><head>"
        '<script type="application/ld+json">'
        f"{json.dumps(jsonld_obj)}"
        "</script>"
        "</head><body>Job body text</body></html>"
    )


# ---------------------------------------------------------------------------
# Known-good ATS shapes
# ---------------------------------------------------------------------------


def test_linkedin_full_jobposting_gbp_annual():
    """LinkedIn ships a full JobPosting with GBP salary and YEAR period."""
    payload = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Senior Backend Engineer",
        "datePosted": "2026-04-01",
        "validThrough": "2026-05-01",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Acme UK Ltd",
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "London",
                "addressCountry": "GB",
            },
        },
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "GBP",
            "value": {
                "@type": "QuantitativeValue",
                "minValue": 75000,
                "maxValue": 95000,
                "unitText": "YEAR",
            },
        },
        "description": "<p>Join our team.</p>",
    }
    result = extract_jsonld_jobposting(_wrap(payload))
    assert isinstance(result, JsonLdExtraction)
    assert result.title == "Senior Backend Engineer"
    assert result.date_posted == date(2026, 4, 1)
    assert result.valid_through == date(2026, 5, 1)
    assert result.hiring_organization_name == "Acme UK Ltd"
    assert result.employment_type == "FULL_TIME"
    assert result.location == "London, GB"
    assert result.salary_min_gbp == 75000
    assert result.salary_max_gbp == 95000
    assert result.salary_period == "annual"
    assert result.description_plain == "Join our team."
    assert "datePosted" in result.raw_fields_present


def test_workday_graph_with_array_employment_type():
    """Workday ships JSON-LD nested under @graph; employmentType is an array."""
    payload = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "Organization", "name": "Parent Co"},
            {
                "@type": "JobPosting",
                "title": "Product Manager",
                "datePosted": "2026-03-15",
                "employmentType": ["FULL_TIME", "PART_TIME"],
                "hiringOrganization": {"name": "Parent Co"},
                "jobLocation": {
                    "address": {
                        "addressLocality": "Manchester",
                        "addressCountry": "GB",
                    }
                },
            },
        ],
    }
    result = extract_jsonld_jobposting(_wrap(payload))
    assert result is not None
    assert result.title == "Product Manager"
    # First element of employmentType array is picked.
    assert result.employment_type == "FULL_TIME"
    assert result.location == "Manchester, GB"


def test_ashby_minimal_no_salary_no_valid_through():
    """Ashby sometimes omits salary and validThrough entirely."""
    payload = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Data Engineer",
        "datePosted": "2026-04-10",
        "hiringOrganization": {"name": "Ashby Co"},
    }
    result = extract_jsonld_jobposting(_wrap(payload))
    assert result is not None
    assert result.title == "Data Engineer"
    assert result.valid_through is None
    assert result.salary_min_gbp is None
    assert result.salary_max_gbp is None
    assert result.salary_period is None


def test_greenhouse_datetime_to_date():
    """Greenhouse ships `datePosted` as a full ISO datetime with timezone."""
    payload = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Frontend Engineer",
        "datePosted": "2026-02-20T10:30:00+00:00",
        "hiringOrganization": {"name": "Greenhouse Co"},
    }
    result = extract_jsonld_jobposting(_wrap(payload))
    assert result is not None
    assert result.date_posted == date(2026, 2, 20)


def test_civil_service_daily_salary():
    """Civil Service Jobs often quotes salary in daily rates."""
    payload = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Senior Civil Servant",
        "datePosted": "2026-04-05",
        "hiringOrganization": {"name": "Cabinet Office"},
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "GBP",
            "value": {
                "@type": "QuantitativeValue",
                "minValue": 450,
                "maxValue": 550,
                "unitText": "DAY",
            },
        },
    }
    result = extract_jsonld_jobposting(_wrap(payload))
    assert result is not None
    assert result.salary_period == "daily"
    assert result.salary_min_gbp == 450
    assert result.salary_max_gbp == 550


def test_indeed_usd_salary_fields_null(caplog):
    """Non-GBP currency → salary fields stay null, DEBUG log emitted."""
    payload = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Engineer (London)",
        "datePosted": "2026-04-12",
        "hiringOrganization": {"name": "US HQ Corp"},
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "USD",
            "value": {
                "@type": "QuantitativeValue",
                "minValue": 110000,
                "maxValue": 140000,
                "unitText": "YEAR",
            },
        },
    }
    import logging
    caplog.set_level(logging.DEBUG, logger="trajectory.sub_agents.jsonld_extractor")
    result = extract_jsonld_jobposting(_wrap(payload))
    assert result is not None
    assert result.title == "Engineer (London)"
    assert result.salary_min_gbp is None
    assert result.salary_max_gbp is None
    assert result.salary_period is None
    assert any("non-GBP" in m.lower() or "usd" in m.lower() for m in caplog.messages)


def test_malformed_json_returns_none():
    """Partial-brace JSON-LD → returns None rather than raising."""
    html = (
        "<html><head>"
        '<script type="application/ld+json">'
        '{"@type": "JobPosting", "title": "Broken"'  # missing closing brace
        "</script>"
        "</head><body></body></html>"
    )
    assert extract_jsonld_jobposting(html) is None


def test_no_jsonld_block_returns_none():
    """HTML with no JSON-LD scripts at all → None."""
    html = "<html><head><title>Plain</title></head><body>Hi</body></html>"
    assert extract_jsonld_jobposting(html) is None


def test_two_jobposting_blocks_returns_first_with_warning(caplog):
    """Two JobPosting blocks → first is returned, warning logged."""
    first = {
        "@type": "JobPosting",
        "title": "First Posting",
        "datePosted": "2026-04-01",
    }
    second = {
        "@type": "JobPosting",
        "title": "Second Posting",
        "datePosted": "2026-04-02",
    }
    html = (
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(first)}</script>'
        f'<script type="application/ld+json">{json.dumps(second)}</script>'
        "</head><body></body></html>"
    )
    import logging
    caplog.set_level(logging.WARNING, logger="trajectory.sub_agents.jsonld_extractor")
    result = extract_jsonld_jobposting(html)
    assert result is not None
    assert result.title == "First Posting"
    assert any("Multiple" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_type_as_array_still_matches():
    """`@type` sometimes a list like ['JobPosting', 'Thing']."""
    payload = {
        "@type": ["JobPosting", "Thing"],
        "title": "Array Type Job",
        "datePosted": "2026-04-01",
    }
    result = extract_jsonld_jobposting(_wrap(payload))
    assert result is not None
    assert result.title == "Array Type Job"


def test_single_value_salary_without_min_max():
    """Some sites ship `value: {value: 80000}` without min/max."""
    payload = {
        "@type": "JobPosting",
        "title": "Single Value Salary",
        "datePosted": "2026-04-01",
        "baseSalary": {
            "currency": "GBP",
            "value": {
                "value": 80000,
                "unitText": "YEAR",
            },
        },
    }
    result = extract_jsonld_jobposting(_wrap(payload))
    assert result is not None
    assert result.salary_min_gbp == 80000
    assert result.salary_max_gbp == 80000


def test_redacted_marker_in_title_rejected():
    """Shield markers in fields → field treated as unusable, returns None."""
    payload = {
        "@type": "JobPosting",
        "title": "Engineer [REDACTED: role_switching]",
        "datePosted": "2026-04-01",
    }
    result = extract_jsonld_jobposting(_wrap(payload))
    assert result is not None
    # Title with shield marker is dropped; other fields remain.
    assert result.title is None
    assert result.date_posted == date(2026, 4, 1)


def test_missing_unittext_defaults_to_annual():
    """Schema.org default is YEAR when unitText is missing."""
    payload = {
        "@type": "JobPosting",
        "title": "Defaulted Period",
        "baseSalary": {
            "currency": "GBP",
            "value": {"minValue": 60000, "maxValue": 70000},
        },
    }
    result = extract_jsonld_jobposting(_wrap(payload))
    assert result is not None
    assert result.salary_period == "annual"


def test_empty_html_returns_none():
    assert extract_jsonld_jobposting("") is None


# ---------------------------------------------------------------------------
# Integration — _extract_jd prepends ground-truth block when jsonld is given
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_jd_prepends_ground_truth_block():
    """When jsonld is passed, the Sonnet user_input starts with a
    GROUND-TRUTH FIELDS block. Mock out the Anthropic call."""
    from trajectory.sub_agents import company_scraper
    from trajectory.schemas import ExtractedJobDescription

    captured: dict[str, str] = {}

    async def fake_call_agent(**kwargs):
        captured["user_input"] = kwargs["user_input"]
        return ExtractedJobDescription(
            role_title="Senior Engineer",
            seniority_signal="senior",
            soc_code_guess="2136",
            soc_code_reasoning="Software development role.",
            location="London",
            remote_policy="hybrid",
            required_skills=["python"],
            posting_platform="linkedin",
            hiring_manager_named=False,
            jd_text_full="Full JD text.",
            specificity_signals=[],
            vagueness_signals=[],
        )

    jsonld = JsonLdExtraction(
        title="Senior Engineer",
        date_posted=date(2026, 4, 1),
        salary_min_gbp=80000,
        salary_max_gbp=100000,
        salary_period="annual",
    )

    with patch.object(company_scraper, "call_agent", fake_call_agent):
        await company_scraper._extract_jd(
            "https://example.com/job/42",
            "Plain JD body text",
            session_id="test-session",
            jsonld=jsonld,
        )

    ui = captured["user_input"]
    assert "GROUND-TRUTH FIELDS FROM SCHEMA.ORG" in ui
    assert "80000" in ui
    assert ui.find("GROUND-TRUTH FIELDS") < ui.find("JOB URL:")


@pytest.mark.asyncio
async def test_extract_jd_no_jsonld_omits_ground_truth_block():
    """jsonld=None → no GROUND-TRUTH block, existing behaviour preserved."""
    from trajectory.sub_agents import company_scraper
    from trajectory.schemas import ExtractedJobDescription

    captured: dict[str, str] = {}

    async def fake_call_agent(**kwargs):
        captured["user_input"] = kwargs["user_input"]
        return ExtractedJobDescription(
            role_title="Role",
            seniority_signal="mid",
            soc_code_guess="2136",
            soc_code_reasoning="r",
            location="London",
            remote_policy="hybrid",
            required_skills=[],
            posting_platform="other",
            hiring_manager_named=False,
            jd_text_full="x",
            specificity_signals=[],
            vagueness_signals=[],
        )

    with patch.object(company_scraper, "call_agent", fake_call_agent):
        await company_scraper._extract_jd(
            "https://example.com/job/99",
            "Plain JD body text",
            session_id=None,
            jsonld=None,
        )

    ui = captured["user_input"]
    assert "GROUND-TRUTH FIELDS" not in ui
    assert ui.startswith("JOB URL:")
