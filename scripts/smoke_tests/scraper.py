"""Smoke test — real URL fetch → JD extraction → company summariser.

Exercises:
  - httpx fetch path (not Playwright — we intentionally pick a plain HTML
    page that doesn't need a headless browser)
  - trafilatura text extraction
  - Phase 1 JD extractor (Sonnet 4.6)
  - Phase 1 company summariser (Sonnet 4.6)
  - Content Shield Tier 1 on scraped bytes

Default URL is the UK gov.uk Civil Service careers listing — stable,
publicly-scrapable, non-JS. Override with SMOKE_SCRAPER_URL if you want
to point at something else.

Cost: ~$0.10 (two Sonnet calls).
"""

from __future__ import annotations

import os

from ._common import (
    SmokeResult,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "scraper"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.10

_DEFAULT_URL = os.getenv(
    "SMOKE_SCRAPER_URL",
    # GitHub careers landing — plain HTML, stable, no JS gate, no anti-bot.
    # Override via SMOKE_SCRAPER_URL if you want to point at a real JD.
    "https://www.github.careers/careers-home/jobs",
)


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()
    missing = require_anthropic_key()
    if missing:
        return [], [missing], 0.0

    from trajectory.sub_agents import company_scraper

    messages: list[str] = []
    failures: list[str] = []

    messages.append(f"URL: {_DEFAULT_URL}")

    try:
        research, jd = await company_scraper.run(
            job_url=_DEFAULT_URL,
            session_id="smoke-scraper",
        )
    except Exception as exc:
        failures.append(f"company_scraper.run raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"ExtractedJobDescription: role={jd.role_title!r}, "
        f"location={jd.location!r}, soc_guess={jd.soc_code_guess!r}, "
        f"required_skills={jd.required_skills[:5]}"
    )
    messages.append(
        f"CompanyResearch: company={research.company_name!r}, "
        f"scraped_pages={len(research.scraped_pages)}, "
        f"culture_claims={len(research.culture_claims)}, "
        f"not_on_careers_page={research.not_on_careers_page}"
    )

    # Basic shape checks
    if not jd.role_title:
        failures.append("JD extractor returned an empty role_title.")
    if not jd.jd_text_full:
        failures.append("JD extractor returned an empty jd_text_full.")
    if not research.scraped_pages:
        failures.append(
            "company_scraper returned no scraped_pages — fetch or "
            "trafilatura extraction silently produced nothing."
        )
    if not research.company_name:
        failures.append("Summariser returned an empty company_name.")

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
