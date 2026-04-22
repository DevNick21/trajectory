"""Phase 1 — Review excerpt scraper.

Scrapes public Glassdoor and Indeed review pages using Playwright.
No RapidAPI. No paid wrappers. Open-source-compatible only.

Returns up to ~10 recent review excerpts for the red_flags detector.
Gracefully returns [] on any failure — reviews are a signal enrichment,
not a hard blocker source.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_TIMEOUT_MS = 20_000
_MAX_REVIEWS = 10


class ReviewExcerpt(BaseModel):
    source: str
    rating: Optional[float] = None
    title: Optional[str] = None
    text: str
    url: Optional[str] = None


# ---------------------------------------------------------------------------
# Playwright helpers
# ---------------------------------------------------------------------------


async def _fetch_page_text(url: str) -> Optional[str]:
    """Fetch a page with Playwright and return its text content."""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_extra_http_headers({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            })
            try:
                await page.goto(url, timeout=_TIMEOUT_MS, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)
                text = await page.inner_text("body")
            finally:
                await browser.close()
            return text
    except Exception as exc:
        logger.debug("Playwright fetch failed for %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Glassdoor scraper
# ---------------------------------------------------------------------------


def _glassdoor_search_url(company_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", company_name.lower()).strip("-")
    return f"https://www.glassdoor.co.uk/Reviews/{slug}-reviews-SRCH_KE0,{len(company_name)}.htm"


def _parse_glassdoor_reviews(text: str, url: str) -> list[ReviewExcerpt]:
    reviews: list[ReviewExcerpt] = []
    if not text:
        return reviews

    # Glassdoor pages interleave review titles and bodies in a predictable
    # text pattern. We extract blocks between star ratings and "Pros"/"Cons".
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # Heuristic: lines following a rating pattern (e.g. "4.0" or "3") that
    # precede "Pros" blocks are review titles.
    i = 0
    while i < len(lines) and len(reviews) < _MAX_REVIEWS:
        line = lines[i]
        # Detect a numeric rating on its own line
        if re.match(r"^\d(\.\d)?$", line):
            rating_val = float(line)
            # Collect the next non-empty line as title, then look for Pros/Cons
            title = lines[i + 1] if i + 1 < len(lines) else ""
            pros = cons = ""
            for j in range(i + 2, min(i + 15, len(lines))):
                if lines[j].lower().startswith("pros"):
                    pros = lines[j + 1] if j + 1 < len(lines) else ""
                elif lines[j].lower().startswith("cons"):
                    cons = lines[j + 1] if j + 1 < len(lines) else ""
            if pros or cons:
                body = f"Pros: {pros}  Cons: {cons}".strip()
                reviews.append(ReviewExcerpt(
                    source="glassdoor",
                    rating=rating_val,
                    title=title or None,
                    text=body,
                    url=url,
                ))
                i += 15
                continue
        i += 1

    return reviews


# ---------------------------------------------------------------------------
# Indeed scraper
# ---------------------------------------------------------------------------


def _indeed_reviews_url(company_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", company_name.lower()).strip("-")
    return f"https://uk.indeed.com/cmp/{slug}/reviews"


def _parse_indeed_reviews(text: str, url: str) -> list[ReviewExcerpt]:
    reviews: list[ReviewExcerpt] = []
    if not text:
        return reviews

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # Indeed review blocks: rating on its own line, then title, then longer body
    i = 0
    while i < len(lines) and len(reviews) < _MAX_REVIEWS:
        line = lines[i]
        if re.match(r"^\d(\.\d)? out of 5", line) or re.match(r"^[1-5]\.?[05]?$", line):
            try:
                rating_val = float(re.search(r"[\d.]+", line).group())  # type: ignore
            except (AttributeError, ValueError):
                rating_val = None
            title = lines[i + 1] if i + 1 < len(lines) else ""
            # Body is typically 2-4 lines after the title
            body_parts = []
            for j in range(i + 2, min(i + 6, len(lines))):
                if len(lines[j]) > 30:
                    body_parts.append(lines[j])
            if body_parts:
                reviews.append(ReviewExcerpt(
                    source="indeed",
                    rating=rating_val,
                    title=title or None,
                    text=" ".join(body_parts),
                    url=url,
                ))
                i += 6
                continue
        i += 1

    return reviews


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


async def fetch(company_name: str) -> list[ReviewExcerpt]:
    """Fetch up to 10 review excerpts from Glassdoor + Indeed.

    Returns [] on any failure — never raises.
    """
    reviews: list[ReviewExcerpt] = []

    # Try Glassdoor first
    gd_url = _glassdoor_search_url(company_name)
    gd_text = await _fetch_page_text(gd_url)
    if gd_text:
        gd_reviews = _parse_glassdoor_reviews(gd_text, gd_url)
        reviews.extend(gd_reviews)
        logger.info("Glassdoor: %d reviews for %r", len(gd_reviews), company_name)
    else:
        logger.info("Glassdoor: no page content for %r", company_name)

    # Try Indeed if we still have room
    if len(reviews) < _MAX_REVIEWS:
        in_url = _indeed_reviews_url(company_name)
        in_text = await _fetch_page_text(in_url)
        if in_text:
            in_reviews = _parse_indeed_reviews(in_text, in_url)
            reviews.extend(in_reviews)
            logger.info("Indeed: %d reviews for %r", len(in_reviews), company_name)
        else:
            logger.info("Indeed: no page content for %r", company_name)

    return reviews[:_MAX_REVIEWS]
