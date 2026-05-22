"""Extract legal-entity hints from scraped company pages.

UK companies are required to publish their registered legal name +
company number on customer-facing pages (Companies Act 2006 §82,
enforced by Companies House Trading Disclosures Regulations 2008).
That mandate is the resolver's ground truth: when we can find the
"Registered in England and Wales No. 12345678" boilerplate in the
scraped footer, we KNOW the CRN. No fuzzy match needed.

This is Layer 4 of the resolver hardening. The flow:
  scraper hits /privacy, /terms, /legal, /about + the JD page
  ->  this module regexes the cleaned text for the disclosure boilerplate
  ->  if a CRN appears, the orchestrator passes it as `crn_hint` to
      resolve_company_identity, which short-circuits to a direct
      /company/{crn} profile fetch — bypassing the fuzzy matcher
      entirely.

When no CRN appears in the scraped text (small employer, marketing-
only site, scrape failure), the resolver falls back to the name +
domain path it always used.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional


logger = logging.getLogger(__name__)


# Companies House registration numbers are 8 alphanumeric chars. The
# vast majority are pure digits (00000001-99999999). Northern Ireland
# uses "NI" prefix, Scotland uses "SC", LLPs use "OC". The pattern
# below covers all four, with the digits being the disambiguating
# part. Word boundaries on both sides prevent matching the middle of
# a longer number (VAT IDs are 9 digits, phone numbers 10-11).
_CRN_TOKEN = r"(?:(?:NI|SC|OC|SO)\d{6}|\d{8})"

# Boilerplate phrases that anchor the CRN. We require a phrase nearby
# to avoid matching arbitrary 8-digit numbers (postcodes are 5-7 chars
# but invoice numbers / order IDs are often 8). Each anchor matches
# the typical UK disclosure variants.
_ANCHORS = [
    r"registered\s+(?:in|under)\s+england(?:\s+and\s+wales)?",
    r"registered\s+(?:in|under)\s+scotland",
    r"registered\s+(?:in|under)\s+northern\s+ireland",
    r"company\s+(?:registration\s+)?(?:no\.?|number)",
    r"reg(?:istered)?\.?\s+(?:no\.?|number)",
    r"companies?\s+house\s+(?:no\.?|number)",
]

# Two patterns: anchor-then-CRN (preferred) and CRN-then-anchor.
# Anchor-then-CRN with up to 80 chars of padding for legal-prose
# variants like "registered in England and Wales with company number".
_ANCHOR_THEN_CRN_RE = re.compile(
    r"(?i)(?:" + "|".join(_ANCHORS) + r")[^.]{0,80}?\b(" + _CRN_TOKEN + r")\b"
)
_CRN_THEN_ANCHOR_RE = re.compile(
    r"(?i)\b(" + _CRN_TOKEN + r")\b[^.]{0,40}?(?:" + "|".join(_ANCHORS) + r")"
)

# Legal-name disclosure. UK companies often state the trading-name to
# registered-name link explicitly: "loveholidays is a trading name of
# We Love Holidays Limited". Capture that.
_TRADING_NAME_RE = re.compile(
    r"(?i)(?:trading\s+name\s+of|a\s+brand\s+of|operated\s+by|owned\s+by)\s+"
    r"([A-Z][A-Za-z0-9 &.,'-]{3,80}?(?:\s+(?:Limited|Ltd\.?|PLC|LLP|LLC|Inc\.?)))"
)


@dataclass
class FooterHints:
    """Structured output of the footer scrape."""

    crn: Optional[str] = None
    legal_name: Optional[str] = None
    source_url: Optional[str] = None

    def is_useful(self) -> bool:
        return bool(self.crn or self.legal_name)


def extract_hints(pages: Iterable["ScrapedPage"]) -> FooterHints:  # type: ignore[name-defined]
    """Scan scraped pages for the UK Trading Disclosures boilerplate.

    Tries each page in order; returns the first hit. Pages are usually
    a short list (the JD page + a few company-info pages) so the
    sequential scan is fine. Returns a FooterHints with the CRN +
    legal_name where found.
    """
    for page in pages:
        text = getattr(page, "text", "") or ""
        url = getattr(page, "url", "") or ""
        if not text:
            continue
        hints = _scan_text(text, source_url=url)
        if hints.is_useful():
            logger.info(
                "Footer hints from %s: crn=%s legal_name=%r",
                url, hints.crn, hints.legal_name,
            )
            return hints
    return FooterHints()


def _scan_text(text: str, *, source_url: Optional[str] = None) -> FooterHints:
    """Run the regex patterns over one page's cleaned text."""
    crn = _find_crn(text)
    legal_name = _find_legal_name(text)
    return FooterHints(crn=crn, legal_name=legal_name, source_url=source_url)


def _find_crn(text: str) -> Optional[str]:
    # Prefer anchor-then-CRN (more specific). Fall back to CRN-then-anchor.
    match = _ANCHOR_THEN_CRN_RE.search(text)
    if match:
        return _normalise_crn(match.group(1))
    match = _CRN_THEN_ANCHOR_RE.search(text)
    if match:
        return _normalise_crn(match.group(1))
    return None


def _find_legal_name(text: str) -> Optional[str]:
    match = _TRADING_NAME_RE.search(text)
    if match:
        return _clean_legal_name(match.group(1))
    return None


def _normalise_crn(raw: str) -> str:
    """Pad pure-digit CRNs to 8 chars; pass through prefixed ones."""
    raw = raw.strip().upper()
    if raw.isdigit():
        return raw.zfill(8)
    return raw


def _clean_legal_name(raw: str) -> str:
    """Trim trailing punctuation and collapse whitespace."""
    cleaned = re.sub(r"\s+", " ", raw).strip()
    cleaned = cleaned.rstrip(".,;:")
    return cleaned
