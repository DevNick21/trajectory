"""Phase 1 — The Gazette insolvency-notice check.

The Gazette is the UK's official public record (Crown Copyright,
free under the Open Government Licence). Insolvency events must be
published here BY LAW. They appear here weeks before press /
Glassdoor / LinkedIn pick them up. Strongest pre-failure signal we
can pull without a paid feed.

API contract (live-verified 2026-05-22):

  Endpoint: https://www.thegazette.co.uk/all-notices/notice/data.json
  Auth:     none (Crown Copyright + OGL)
  Filter:   `service=insolvency` narrows to the Insolvency Gazette
  Query:    `text={company}` matches across the notice body

  Response shape:
    {
      "f:total": <int>,
      "entry": [
        {
          "id":        "https://www.thegazette.co.uk/...",
          "title":     "The London Gazette, Issue N, Page P",
          "link":      [{"@href": ".../data.pdf", "@rel": "self"}, ...],
          "published": "YYYY-MM-DDT00:00:00",
          "updated":   "YYYY-MM-DDT...",
          "content":   "<div ...>...HTML body...</div>",
          "author":    {"name": "tso"},
        },
        ...
      ]
    }

  CRITICAL: there is NO `notice-code` field at the entry level. The
  notice type is encoded as a phrase inside the `content` HTML
  ("Winding-Up Petition", "Members' Voluntary Winding-up", "Notice
  of Appointment of Administrators", etc.). We classify by matching
  phrase patterns to the canonical Gazette notice codes.

  Likewise the company name is inside `content`, not `title`. We
  extract the first all-caps run, optionally followed by
  "(in Administration)" / "(in Liquidation)" / similar markers.
"""

from __future__ import annotations

import logging
import re
from datetime import date as _date, datetime
from html import unescape
from typing import Any, Optional

import httpx

from ..schemas import GazetteSignal

logger = logging.getLogger(__name__)


_BASE = "https://www.thegazette.co.uk"
_SEARCH_PATH = "/all-notices/notice/data.json"
_TIMEOUT = 12.0


# Generic "insolvency-event" code used when service=insolvency
# returns an entry but the body text doesn't carry one of the
# specific phrases below (very common — many Gazette publications
# are bundled "Notices of Compulsory Strike-Off" / "Liquidation
# Listings" supplements that just enumerate company names without
# the inline phrase). Trust the service-filter: any entry that
# came back under `service=insolvency` IS an insolvency notice,
# even if we can't sharper-classify it.
_GENERIC_INSOLVENCY_CODE = "2400"
_GENERIC_INSOLVENCY_LABEL = "Insolvency Notice (unclassified)"


# Notice-type phrase patterns → canonical Gazette notice codes. Order
# matters: more-specific patterns first so "Winding-Up Petition" doesn't
# also match the generic "Winding Up" rule below it.
_NOTICE_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # Notice 2450/2451 — creditor winding-up petitions (the strongest
    # pre-failure signal in the corpus).
    (
        re.compile(r"(?i)\bwinding[\s-]*up\s+petition\b"),
        "2450",
        "Winding-Up Petition",
    ),
    (
        re.compile(r"(?i)\bpetition\s+to\s+wind\s+up\b"),
        "2450",
        "Winding-Up Petition",
    ),
    # Notice 2410 — appointment of administrators
    (
        re.compile(r"(?i)\bappointment\s+of\s+(?:joint\s+)?administrators?\b"),
        "2410",
        "Appointment of Administrators",
    ),
    (
        re.compile(r"(?i)\bin\s+administration\b"),
        "2410",
        "Appointment of Administrators",
    ),
    # Notice 2441 — voluntary winding up (creditors' or members')
    (
        re.compile(r"(?i)\b(?:members'?|creditors'?)\s+voluntary\s+winding[\s-]*up\b"),
        "2441",
        "Resolution for Voluntary Winding Up",
    ),
    (
        re.compile(r"(?i)\bresolution(?:s)?\s+for\s+winding[\s-]*up\b"),
        "2441",
        "Resolution for Voluntary Winding Up",
    ),
    # Notice 2440 — compulsory winding-up (court order)
    (
        re.compile(r"(?i)\bcompulsory\s+winding[\s-]*up\b"),
        "2440",
        "Compulsory Winding-Up Order",
    ),
    (
        re.compile(r"(?i)\bwinding[\s-]*up\s+order\b"),
        "2440",
        "Compulsory Winding-Up Order",
    ),
    # Notice 2460/2461 — liquidator appointment
    (
        re.compile(r"(?i)\bappointment\s+of\s+(?:joint\s+)?liquidators?\b"),
        "2460",
        "Notice of Appointment of Liquidator",
    ),
    # Notice 2480 — dissolution
    (
        re.compile(r"(?i)\bnotice\s+of\s+dissolution\b"),
        "2480",
        "Notice of Dissolution",
    ),
    # Bare "winding up" — catches the older-style notices that just say
    # "Winding-Up" without specifying the route. Lowest specificity so
    # last in the chain. Treated as a voluntary winding up by default.
    (
        re.compile(r"(?i)\bwinding[\s-]*up\b"),
        "2441",
        "Winding Up (unspecified route)",
    ),
]


# Codes that are the strongest pre-failure signal; the verdict treats
# any active one as a hard blocker.
HARD_BLOCKER_CODES = {"2410", "2440", "2441", "2450", "2451"}


# Strip HTML tags out of the `content` field. The Gazette's JSON
# encodes content as embedded XHTML inside a wrapping <div>. We don't
# need the markup, just the text to regex against.
_TAG_RE = re.compile(r"<[^>]+>")


def _content_to_text(content: Any) -> str:
    """Coerce the JSON content field to plain text.

    The Gazette serialises content as either:
      - a string of escaped HTML, OR
      - an object {"@type": "xhtml", "div": {...}} (rarer)

    Both flow through here. We strip tags + unescape entities and
    collapse whitespace.
    """
    if not content:
        return ""
    if isinstance(content, dict):
        # Try common shapes: {"div": ...} or {"#text": ...} or
        # {"$": ...} (XML-to-JSON convention)
        for key in ("#text", "$", "div", "value"):
            if key in content:
                return _content_to_text(content[key])
        # Last resort: serialise the dict to text via its values
        return _content_to_text(" ".join(
            str(v) for v in content.values() if isinstance(v, (str, dict))
        ))
    text = unescape(str(content))
    text = _TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


# Common patterns for capturing the subject company name out of the
# notice body. Notices typically open with the company name in caps,
# often followed by a status marker in parentheses.
_COMPANY_PATTERNS = [
    # "ACME WIDGETS LIMITED (in Administration)"
    re.compile(
        r"\b([A-Z][A-Z0-9 &',./\-]{2,80}?\s+(?:LIMITED|LTD\.?|PLC|LLP|LLC))\b"
        r"\s*\((?:in\s+)?(?:administration|liquidation|receivership)",
        re.IGNORECASE,
    ),
    # "Re ACME WIDGETS LIMITED" / "In the matter of ACME WIDGETS LIMITED"
    re.compile(
        r"(?:Re|In\s+the\s+matter\s+of)\s+([A-Z][A-Z0-9 &',./\-]{2,80}?\s+(?:LIMITED|LTD\.?|PLC|LLP|LLC))\b",
        re.IGNORECASE,
    ),
    # Bare all-caps company name at start: "ACME WIDGETS LIMITED ..."
    re.compile(
        r"^\s*([A-Z][A-Z0-9 &',./\-]{2,80}?\s+(?:LIMITED|LTD\.?|PLC|LLP|LLC))\b",
        re.IGNORECASE,
    ),
]


def _extract_company_name(text: str) -> Optional[str]:
    """Pull the subject company name from the notice body text."""
    if not text:
        return None
    # Trim leading metadata ("The London Gazette, Issue N..." sometimes
    # prefixes the content text rendering).
    head = text[:1000]
    for pattern in _COMPANY_PATTERNS:
        match = pattern.search(head)
        if match:
            name = re.sub(r"\s+", " ", match.group(1)).strip()
            return name
    return None


def _classify_notice(text: str) -> tuple[str, str]:
    """Return (notice_code, notice_type) for the first phrase pattern
    that matches, defaulting to the generic insolvency code when no
    specific phrase fits.

    Calling this means you've already filtered to insolvency-service
    entries — so the question isn't "is this insolvency?" (yes) but
    "WHICH KIND of insolvency event?". When the body text doesn't say,
    we still emit a signal at the generic severity rather than dropping
    a real insolvency event silently.
    """
    if text:
        for pattern, code, label in _NOTICE_PATTERNS:
            if pattern.search(text):
                return code, label
    return _GENERIC_INSOLVENCY_CODE, _GENERIC_INSOLVENCY_LABEL


async def _search(name: str, *, page_size: int = 20) -> dict:
    """Query The Gazette's JSON search. Returns the raw envelope or {}."""
    params = {
        "text": name,
        "service": "insolvency",
        "results-page-size": page_size,
    }
    try:
        async with httpx.AsyncClient(base_url=_BASE, timeout=_TIMEOUT) as client:
            resp = await client.get(_SEARCH_PATH, params=params)
            if resp.status_code != 200:
                logger.info(
                    "Gazette search returned %d for %r", resp.status_code, name,
                )
                return {}
            try:
                return resp.json()
            except ValueError:
                logger.info("Gazette search returned non-JSON for %r", name)
                return {}
    except Exception as exc:
        logger.warning("Gazette search failed for %r: %s", name, exc)
        return {}


def _entries(envelope: dict) -> list[dict]:
    """Pull the entry list out of a Gazette response envelope.

    The Gazette uses `entry` (singular) for results. Older endpoints
    we tried (`notices`, `items`) don't exist — we keep the fallback
    chain in case the API surfaces a different shape in future, but
    `entry` is the live answer.
    """
    raw = envelope.get("entry")
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):  # single-entry result envelopes
        return [raw]
    # Belt-and-braces — try the keys we'd see on a paged variant.
    for key in ("entries", "notices", "items", "results", "data"):
        candidate = envelope.get(key)
        if isinstance(candidate, list):
            return candidate
    return []


def _parse_entry(entry: dict) -> Optional[tuple[GazetteSignal, str]]:
    """Coerce one Gazette entry into (GazetteSignal, body_text), or
    None if the entry is too sparse to use.

    Returns the body text alongside the signal so the caller can
    apply target-name filtering against the raw notice text — not
    just the extracted company_name_on_notice (which is unreliable
    in bundled multi-company supplements).
    """
    body = _content_to_text(entry.get("content"))
    if not body:
        return None
    code, label = _classify_notice(body)

    pub_str = entry.get("published") or entry.get("updated")
    published_at: Optional[_date] = None
    if pub_str:
        try:
            published_at = datetime.fromisoformat(
                str(pub_str).rstrip("Z").split("+")[0]
            ).date()
        except ValueError:
            pass

    notice_id = entry.get("id")
    url: Optional[str] = None
    if isinstance(entry.get("link"), list) and entry["link"]:
        first_link = entry["link"][0]
        if isinstance(first_link, dict):
            href = first_link.get("@href") or first_link.get("href")
            if href:
                url = href if href.startswith("http") else f"{_BASE}{href}"
    if not url and notice_id:
        url = str(notice_id)

    signal = GazetteSignal(
        notice_code=code,
        notice_type=label,
        published_at=published_at,
        notice_id=str(notice_id) if notice_id else None,
        url=url,
        company_name_on_notice=_extract_company_name(body),
        active=True,
    )
    return signal, body


def _matches_target(
    signal: GazetteSignal,
    *,
    raw_notice_text: str,
    query_terms: list[str],
    crn: Optional[str] = None,
) -> bool:
    """Strict filter: does this notice actually concern our target?

    Two levels of matching, in priority order:

    1. **CRN match (preferred).** The Gazette prints the Companies
       House registration number directly next to each company name
       in bundled strike-off lists (e.g. "WILKO LIMITED 09563205").
       When the resolver has anchored a CRN, requiring it to appear
       in the notice body gives us EXACT-entity matching — no risk of
       confusing the trading entity with a sibling shell that shares
       the brand name.

    2. **Whole-word name match (fallback).** When we don't have a CRN,
       we fall back to requiring the canonical name to appear as a
       complete substring of the body. This is still strict (no fuzzy
       matching) but cannot distinguish between sibling entities.

    Net effect: when a CRN is available the agent is HIGH-precision
    HIGH-recall. Without a CRN it's high-precision but the user must
    not treat its signals as hard-blocker-quality.
    """
    haystack = raw_notice_text.upper()

    # Level 1 — CRN match. 8-digit run anchored on word boundaries.
    # CH numbers are normally rendered as 8 digits but historic ones
    # can be padded ("00365335") or unpadded ("365335"). We try both
    # the supplied form and the zero-padded form.
    if crn:
        candidates_crn = {crn.strip()}
        if crn.isdigit():
            candidates_crn.add(crn.zfill(8))
            candidates_crn.add(str(int(crn)))  # unpadded
        for c in candidates_crn:
            if re.search(r"\b" + re.escape(c) + r"\b", haystack):
                return True
        # CRN supplied but not found in the body — refuse the match.
        # This is the loveholidays-class fix: when the resolver knows
        # the trading entity's CRN AND the notice doesn't mention it,
        # the notice is about a DIFFERENT company sharing the brand.
        return False

    # Level 2 — name match (no CRN to anchor on). Require a
    # whole-word match. Anything under 4 chars is statistically
    # noise across the bundle corpus.
    if not query_terms:
        return False
    candidates = [t.strip() for t in query_terms if t and len(t.strip()) >= 4]
    if not candidates:
        return False
    for term in candidates:
        needle_upper = term.upper()
        if re.search(r"\b" + re.escape(needle_upper) + r"\b", haystack):
            return True
        # Try the suffix-stripped form too.
        stripped = re.sub(
            r"\s+(?:LIMITED|LTD\.?|PLC|LLP|LLC|INC\.?|CORP\.?)\b",
            "",
            needle_upper,
        ).strip()
        if stripped and stripped != needle_upper:
            if re.search(r"\b" + re.escape(stripped) + r"\b", haystack):
                return True
    return False


def _dedupe(signals: list[GazetteSignal]) -> list[GazetteSignal]:
    """Drop duplicates by notice_id (preferred) or (code, date, company)."""
    seen: set[tuple] = set()
    unique: list[GazetteSignal] = []
    for s in signals:
        key: tuple
        if s.notice_id:
            key = ("id", s.notice_id)
        else:
            key = (
                "ck", s.notice_code, str(s.published_at),
                s.company_name_on_notice,
            )
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)
    unique.sort(key=lambda s: s.published_at or _date.min, reverse=True)
    return unique


async def check(
    *,
    company_name: str,
    canonical_name: Optional[str] = None,
    crn: Optional[str] = None,
) -> list[GazetteSignal]:
    """Return insolvency notices for the company. Empty list if none.

    Searches under both the canonical name (when the resolver supplied
    one) and the raw JD name. Cross-checks the matched company name on
    each notice against the queries so loose text-search matches don't
    leak through as false positives.
    """
    queries: list[str] = []
    if canonical_name:
        queries.append(canonical_name)
    if company_name and company_name not in queries:
        queries.append(company_name)
    if not queries:
        return []

    # Recency cut-off — Gazette insolvency archives go back to the
    # 1800s. Historical strike-offs of long-defunct subsidiaries don't
    # tell us anything about the company hiring today. 24 months is a
    # generous window that catches the typical pre-collapse signal
    # without surfacing decades-old housekeeping.
    from datetime import timedelta
    recency_cutoff = _date.today() - timedelta(days=730)

    # Bundled multi-company strike-off supplements are common in the
    # Gazette and they're noisy: a single entry can incidentally mention
    # the target's CRN or canonical name without that company actually
    # being the subject of a wind-up. To avoid surfacing those:
    #   - "Specific" notice codes (2410/2440/2441/2450/2451/2460/2480)
    #     are always emitted when target-matched. These are unambiguous.
    #   - "Generic" 2400 codes are emitted ONLY when a CRN match
    #     confirmed it AND the body is short enough that the
    #     company-list-bundle pattern is unlikely.
    # This trade-off favours precision over recall — false positives are
    # more harmful than missed signals (the rest of the distress matrix
    # picks up genuine trouble).
    _BUNDLED_LIST_BODY_THRESHOLD = 2000  # chars

    candidates: list[GazetteSignal] = []
    for q in queries:
        envelope = await _search(q)
        for entry in _entries(envelope):
            if not isinstance(entry, dict):
                continue
            parsed = _parse_entry(entry)
            if not parsed:
                continue
            signal, body_text = parsed
            if signal.published_at and signal.published_at < recency_cutoff:
                continue
            if not _matches_target(
                signal,
                raw_notice_text=body_text,
                query_terms=queries,
                crn=crn,
            ):
                continue
            # Generic-classification + long-body = almost certainly a
            # bundled supplement. Skip to keep the signal high-precision.
            if (
                signal.notice_code == _GENERIC_INSOLVENCY_CODE
                and len(body_text) > _BUNDLED_LIST_BODY_THRESHOLD
            ):
                continue
            candidates.append(signal)

    deduped = _dedupe(candidates)
    if deduped:
        logger.info(
            "Gazette: %d insolvency notice(s) for %r (canonical=%r, crn=%s)",
            len(deduped), company_name, canonical_name, crn,
        )
    return deduped


def has_hard_blocker(signals: list[GazetteSignal]) -> Optional[GazetteSignal]:
    """Return the first active signal that warrants a hard blocker, or None."""
    for s in signals:
        if s.active and s.notice_code in HARD_BLOCKER_CODES:
            return s
    return None
