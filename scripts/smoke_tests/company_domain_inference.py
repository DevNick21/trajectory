"""Smoke: company-domain inference from ATS-hosted JD URLs.

Tests the inference path that makes Companies Act §82 footer-CRN
extraction reachable for the loveholidays-class case: JD lives on
jobs.ashbyhq.com/loveholidays/... but the CRN disclosure lives on
loveholidays.com/privacy. Without inference, the scraper never sees
the company's own pages and the resolver falls through to lossy
name-fuzzy-matching.

No live network — `_domain_is_live` is stubbed so the test asserts
the logic, not the live availability of any real domain.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from ._common import SmokeResult, prepare_environment, run_smoke

NAME = "company_domain_inference"
ESTIMATED_COST_USD = 0.0


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()
    messages: list[str] = []
    failures: list[str] = []

    from askpicky.sub_agents import company_scraper as cs

    # Stub _domain_is_live: pretend any 3+ char domain in this set is
    # live, everything else dead. Covers the loveholidays + several
    # other realistic patterns without touching the network.
    LIVE = {
        "loveholidays.com",
        "monzo.com",
        "wise.com",
        "octopus.energy",
        "octopusenergy.com",
        "deliveroo.co.uk",
    }

    async def _fake_live(domain: str) -> bool:
        return domain in LIVE

    original_live = cs._domain_is_live
    cs._domain_is_live = _fake_live

    cases = [
        # (url, expected_domain, label)
        (
            "https://jobs.ashbyhq.com/loveholidays/80aef5f9-efe1-459f-aea6-2d86f5280bea",
            "loveholidays.com",
            "Ashby /{slug}/ — loveholidays",
        ),
        (
            "https://boards.greenhouse.io/monzo/jobs/123456",
            "monzo.com",
            "Greenhouse /{slug}/jobs/",
        ),
        (
            "https://jobs.lever.co/wise/abc-def",
            "wise.com",
            "Lever /{slug}/",
        ),
        (
            "https://deliveroo.bamboohr.com/careers/100",
            "deliveroo.co.uk",  # .com isn't in our LIVE set; .co.uk is
            "BambooHR subdomain — Deliveroo (.co.uk fallback)",
        ),
        (
            "https://octopusenergy.pinpointhq.com/jobs/eng-001",
            "octopusenergy.com",
            "Pinpoint subdomain — hyphen-stripped",
        ),
        (
            "https://www.example-not-an-ats.com/jobs/123",
            "example-not-an-ats.com",
            "Own-site JD (Layer 1)",
        ),
        (
            "https://uk.indeed.com/viewjob?jk=abc",
            None,
            "LinkedIn/Indeed style — no slug recoverable",
        ),
    ]

    try:
        for url, expected, label in cases:
            picked = await cs._infer_company_domain(url)
            if picked != expected:
                failures.append(
                    f"{label}: {url!r} -> {picked!r}, expected {expected!r}"
                )
            else:
                messages.append(f"{label}: {picked!r}")

        # Hyphen-stripped candidate ordering — for slug "we-love-holidays"
        # the bare form should be tried first (shorter form wins on the
        # sort key in _candidate_brand_domains).
        cands = cs._candidate_brand_domains("we-love-holidays")
        if not cands or cands[0] != "weloveholidays.com":
            failures.append(
                f"_candidate_brand_domains('we-love-holidays')[0] = "
                f"{cands[:1]!r}, expected weloveholidays.com first"
            )
        else:
            messages.append(
                f"candidate ordering: {cands[:2]} (hyphen-stripped first)"
            )

        # ATS slug extraction on each known host shape — without network.
        slug_cases = [
            ("https://jobs.ashbyhq.com/loveholidays/abc", "loveholidays"),
            ("https://boards.greenhouse.io/monzo/jobs/123", "monzo"),
            ("https://jobs.lever.co/wise/abc", "wise"),
            (
                "https://deliveroo.wd1.myworkdayjobs.com/careers/abc",
                "deliveroo",
            ),
            (
                "https://apply.workable.com/pleo/j/123",
                "pleo",
            ),
            ("https://www.acme-corp.com/jobs/123", None),  # not an ATS
            ("https://uk.indeed.com/viewjob?jk=abc", None),
        ]
        for url, expected_slug in slug_cases:
            slug = cs._extract_ats_slug(url)
            if slug != expected_slug:
                failures.append(
                    f"_extract_ats_slug({url!r}) -> {slug!r}, "
                    f"expected {expected_slug!r}"
                )
        if not failures:
            messages.append(
                f"ATS slug extraction: {len(slug_cases)} URL shapes OK"
            )
    finally:
        cs._domain_is_live = original_live

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
