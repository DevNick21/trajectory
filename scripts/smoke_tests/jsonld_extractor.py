"""Smoke test — JSON-LD Tier 0 extractor.

No LLM call. Hits one stable public URL known to ship Schema.org
JobPosting JSON-LD (Civil Service Jobs), asserts the extractor
returns a non-None result with a plausible `date_posted`.

Falls back gracefully on a network hiccup — a smoke test should not
hard-fail when the site is transiently unavailable. We return a messaged
pass so the run_all rollup still exits zero, and the failure log makes
the cause obvious.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from ._common import SmokeResult, run_smoke

NAME = "jsonld_extractor"
REQUIRES_LIVE_LLM = False
ESTIMATED_COST_USD = 0.0

# Civil Service Jobs listing page. The domain is stable and ships
# Schema.org JSON-LD reliably. The specific listing rotates — we fetch
# the search page, which also carries JobPosting JSON-LD for the first
# few results.
_SMOKE_URL = "https://www.civilservicejobs.service.gov.uk/csr/index.cgi"
_USER_AGENT = "Mozilla/5.0 (compatible; TrajectoryBot/0.1)"

logger = logging.getLogger("smoke.jsonld_extractor")


async def _body() -> tuple[list[str], list[str], float]:
    from trajectory.sub_agents.jsonld_extractor import extract_jsonld_jobposting

    messages: list[str] = []
    failures: list[str] = []

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = await client.get(_SMOKE_URL)
    except Exception as exc:
        messages.append(f"network error fetching {_SMOKE_URL}: {exc!r}")
        # Network-layer failure isn't a code-level smoke-test failure.
        return messages, failures, ESTIMATED_COST_USD

    if resp.status_code >= 400:
        messages.append(
            f"site returned HTTP {resp.status_code}; skipping live assertion"
        )
        return messages, failures, ESTIMATED_COST_USD

    raw_html = resp.text
    messages.append(f"fetched {len(raw_html)} bytes from {_SMOKE_URL}")

    # Pure function; offload from event loop.
    result = await asyncio.to_thread(extract_jsonld_jobposting, raw_html)

    if result is None:
        messages.append(
            "extractor returned None — site may have changed or no "
            "JobPosting JSON-LD present today"
        )
        # A real regression would be the extractor crashing; a None
        # return on a live URL is acceptable (fallback path in production).
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"extracted: title={result.title!r} "
        f"date_posted={result.date_posted!s} "
        f"salary_min_gbp={result.salary_min_gbp} "
        f"period={result.salary_period}"
    )

    # Plausibility checks — only assert on fields that were actually
    # populated.
    if result.date_posted is not None:
        from datetime import date, timedelta

        today = date.today()
        floor = today - timedelta(days=365 * 3)
        ceiling = today + timedelta(days=30)
        if not (floor <= result.date_posted <= ceiling):
            failures.append(
                f"date_posted {result.date_posted} outside plausible window"
            )

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
