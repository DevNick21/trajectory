"""Firecrawl integration — targeted fallback for anti-bot pages.

Only used when the primary fetch (httpx / Playwright) returns empty or
blocked. Firecrawl charges 1 credit per scraped page (free tier = 1,000
pages/month, Hobby = 5,000 pages for $16/mo).

Docs: https://docs.firecrawl.dev/api-reference/scrape
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from .config import settings
from .validators.url_safety import UnsafeURL, validate_public_fetch_url

logger = logging.getLogger(__name__)

# Hosts known to aggressively bot-protect — route directly to Firecrawl
# instead of failing through httpx → Playwright → nothing.
_ANTI_BOT_HOSTS: set[str] = {
    "glassdoor.com",
    "glassdoor.co.uk",
    "indeed.com",
    "linkedin.com",
    "reed.co.uk",
    "totaljobs.com",
    "cv-library.co.uk",
    "monster.co.uk",
    "monster.com",
}

# Minimum character count for a page to be considered "valid" — anything
# below this is likely a bot challenge, CloudFlare wall, or empty response.
_MIN_CONTENT_CHARS = 200

# Standard fetch timeout — generous because Firecrawl may proxy through
# a full headless browser.
_FIRECRAWL_TIMEOUT = 30.0


async def firecrawl_scrape(
    url: str,
    *,
    user_id: Optional[str] = None,
    storage: Optional[Any] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Scrape a single URL via Firecrawl. Returns cleaned text or None.

    Charges 1 credit per page. Only call this as a fallback when the
    primary fetch path has already failed and the page is critical for
    verdict or red-flag evidence.
    """
    try:
        url = await validate_public_fetch_url(url)
    except UnsafeURL as exc:
        logger.warning("Blocked unsafe Firecrawl URL %s: %s", url, exc)
        return None

    if not settings.firecrawl_api_key:
        logger.warning(
            "FIRECRAWL_API_KEY not set — skipping Firecrawl fallback for %s",
            url,
        )
        return None
    if settings.enforce_hosted_quotas and user_id and storage is not None:
        quota = await storage.record_quota_usage(
            user_id=user_id,
            category="firecrawl",
            units=1,
            metadata={"url": url, **(metadata or {})},
        )
        if not quota["allowed"]:
            logger.warning(
                "Firecrawl quota exceeded for user=%s period=%s used=%s limit=%s",
                user_id,
                quota["period"],
                quota["used"],
                quota["limit"],
            )
            return None

    endpoint = f"{settings.firecrawl_base_url.rstrip('/')}/scrape"
    headers = {
        "Authorization": f"Bearer {settings.firecrawl_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": url,
        "formats": ["markdown"],
        "waitFor": 3000,  # ms — let JS render
        "timeout": 15000,  # ms
    }

    try:
        async with httpx.AsyncClient(timeout=_FIRECRAWL_TIMEOUT) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
            if resp.status_code >= 400:
                logger.warning(
                    "Firecrawl returned %d for %s: %s",
                    resp.status_code, url, resp.text[:200],
                )
                return None
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Firecrawl request failed for %s: %s", url, exc)
        return None

    # Prefer markdown; fall back to raw HTML.
    markdown = (data.get("data") or {}).get("markdown")
    if markdown and isinstance(markdown, str) and len(markdown.strip()) > 50:
        return markdown.strip()

    # Firecrawl sometimes returns rawHtml instead.
    raw_html = (data.get("data") or {}).get("rawHtml")
    if raw_html and isinstance(raw_html, str):
        return raw_html

    logger.warning("Firecrawl response for %s had no usable content", url)
    return None


def is_anti_bot_host(url: str) -> bool:
    """Check if the URL host is a known anti-bot domain."""
    try:
        host = urlparse(url).hostname or ""
        return any(
            host == blocked or host.endswith("." + blocked)
            for blocked in _ANTI_BOT_HOSTS
        )
    except Exception:
        return False


def is_thin_content(text: Optional[str]) -> bool:
    """True if the text is empty, too short, or looks like a bot challenge.

    Pages under _MIN_CONTENT_CHARS chars are likely CloudFlare walls,
    captcha prompts, or empty 403 responses — not usable for verdict/
    extraction. Firecrawl should be tried as a fallback.
    """
    if not text:
        return True
    stripped = text.strip()
    if len(stripped) < _MIN_CONTENT_CHARS:
        return True
    # Bot-challenge patterns that slip through Playwright
    challenge_markers = (
        "verify you are a human",
        "are you a robot",
        "cf-challenge",
        "cloudflare",
        "checking your browser",
        "please enable javascript",
        "captcha",
        "ddos-guard",
        "perimeterx",
    )
    lower = stripped.lower()
    if any(m in lower for m in challenge_markers):
        # Only flag if the content is thin — a legitimate page that
        # happens to mention CloudFlare won't trigger this.
        if len(stripped) < 2000:
            return True
    return False
