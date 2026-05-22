"""Phase 1 — The Gazette insolvency-notice check.

The Gazette is the UK's official public record (Crown Copyright,
free under the Open Government Licence). Insolvency events — petitions,
administrator appointments, winding-up resolutions — must be published
here by law. They appear WEEKS before the same event surfaces in
press / Glassdoor / LinkedIn.

This is the strongest pre-failure signal we can pull without a paid
data feed. Free API, no key required, no rate limit we've hit.

We search for the canonical legal name (preferred — supplied by the
resolver) and the JD's raw name as a fallback. Notices come back
typed by code:

  2410 — Appointment of Administrators
  2441 — Resolutions for Winding Up
  2450 — Winding-Up Petitions (creditor-filed)
  Plus 2400s family of related insolvency notices.

Any ACTIVE notice in the 2400s for the resolved company is a hard
blocker in the verdict's matrix.
"""

from __future__ import annotations

import logging
from datetime import date as _date, datetime
from typing import Any, Optional

import httpx

from ..schemas import GazetteSignal

logger = logging.getLogger(__name__)


_BASE = "https://www.thegazette.co.uk"
_TIMEOUT = 12.0


# Notice codes the resolver treats as distress. Source: The Gazette's
# notice-type taxonomy. Codes are stable across the publication.
_INSOLVENCY_CODES = {
    "2410": "Appointment of Administrators",
    "2411": "Notice of Statement of Affairs (administration)",
    "2415": "Administrators' progress report",
    "2418": "Notice of end of administration",
    "2440": "Compulsory Winding-Up Order",
    "2441": "Resolution for Voluntary Winding Up",
    "2442": "Members' Voluntary Winding Up",
    "2450": "Winding-Up Petition",
    "2451": "Winding-Up Petition (court order)",
    "2460": "Notice of Appointment of Liquidator",
    "2461": "Notice of Appointment of Joint Liquidators",
    "2470": "Notice of Final Meeting (liquidation)",
    "2480": "Notice of Dissolution",
}

# Subset that's the strongest pre-failure signal — these warrant a
# verdict-level hard blocker. The full _INSOLVENCY_CODES set is
# surfaced; the hard-blocker decision in the verdict checks against
# these specifically.
HARD_BLOCKER_CODES = {"2410", "2440", "2441", "2450", "2451"}


async def _search(
    name: str, *, limit: int = 20,
) -> list[dict[str, Any]]:
    """Query the Gazette search API for the company name.

    No API key. Content negotiation via Accept header — returns JSON
    when we ask for it.
    """
    params = {
        "q": name,
        # The Gazette has three regional editions (London / Edinburgh /
        # Belfast). London covers England + Wales; the others cover
        # Scotland and NI respectively. We don't filter here — let the
        # caller decide based on the resolved registered office.
        "limit": limit,
    }
    headers = {"Accept": "application/json"}
    try:
        async with httpx.AsyncClient(
            base_url=_BASE, timeout=_TIMEOUT,
        ) as client:
            resp = await client.get(
                "/all-notices/notice", params=params, headers=headers,
            )
            if resp.status_code != 200:
                logger.info(
                    "Gazette search returned %d for %r", resp.status_code, name,
                )
                return []
            try:
                payload = resp.json()
            except ValueError:
                logger.info("Gazette search returned non-JSON for %r", name)
                return []
    except Exception as exc:
        logger.warning("Gazette search failed for %r: %s", name, exc)
        return []

    # The Gazette's JSON shape varies a bit between endpoints. Be
    # defensive: pull notices from any of the common envelope keys.
    if isinstance(payload, dict):
        for key in ("notices", "items", "results", "entries", "data"):
            raw = payload.get(key)
            if isinstance(raw, list):
                return raw
        # Single-notice shape — wrap.
        if payload.get("notice-code") or payload.get("notice_id"):
            return [payload]
    if isinstance(payload, list):
        return payload
    return []


def _parse_notice(raw: dict[str, Any]) -> Optional[GazetteSignal]:
    """Coerce one Gazette JSON record into a GazetteSignal.

    The Gazette publishes RDF-flavoured JSON with several possible
    key spellings. We try the obvious variants and fall through to
    None when the record doesn't carry an insolvency code we care about.
    """
    code = (
        str(raw.get("notice-code")
            or raw.get("notice_code")
            or raw.get("noticeCode")
            or raw.get("code")
            or "").strip()
    )
    if code not in _INSOLVENCY_CODES:
        return None

    company_name = (
        raw.get("company-name")
        or raw.get("company_name")
        or raw.get("subject")
        or raw.get("title")
        or None
    )

    pub_str = (
        raw.get("publish-date")
        or raw.get("publication_date")
        or raw.get("publishDate")
        or raw.get("date_of_publication")
        or raw.get("date")
        or None
    )
    published_at: Optional[_date] = None
    if pub_str:
        try:
            published_at = datetime.strptime(
                str(pub_str)[:10], "%Y-%m-%d",
            ).date()
        except ValueError:
            pass

    notice_id = (
        raw.get("id") or raw.get("notice_id") or raw.get("noticeId") or None
    )
    url = raw.get("url") or raw.get("link") or None
    if url and isinstance(url, str) and url.startswith("/"):
        url = f"{_BASE}{url}"
    elif not url and notice_id:
        url = f"{_BASE}/notice/{notice_id}"

    return GazetteSignal(
        notice_code=code,
        notice_type=_INSOLVENCY_CODES[code],
        published_at=published_at,
        notice_id=str(notice_id) if notice_id else None,
        url=url,
        company_name_on_notice=company_name,
        active=True,
    )


def _dedupe(signals: list[GazetteSignal]) -> list[GazetteSignal]:
    """Drop duplicates by (notice_id) or (code + published_at + company)."""
    seen: set[tuple] = set()
    unique: list[GazetteSignal] = []
    for s in signals:
        if s.notice_id:
            key = ("id", s.notice_id)
        else:
            key = ("ck", s.notice_code, str(s.published_at), s.company_name_on_notice)
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)
    # Most recent first — surfaces the most-actionable petition top of list.
    unique.sort(
        key=lambda s: s.published_at or _date.min, reverse=True,
    )
    return unique


async def check(
    *,
    company_name: str,
    canonical_name: Optional[str] = None,
    crn: Optional[str] = None,
) -> list[GazetteSignal]:
    """Return insolvency notices for the company. Empty list if none.

    Pulls under two anchors (the canonical name from the resolver +
    the raw JD name) so we catch both legal-name and brand filings.
    The CRN is currently used only for the trace + future per-CRN
    cache; the Gazette API doesn't index by CRN directly.
    """
    queries: list[str] = []
    if canonical_name:
        queries.append(canonical_name)
    if company_name and company_name not in queries:
        queries.append(company_name)
    if not queries:
        return []

    notices: list[GazetteSignal] = []
    for q in queries:
        raw_list = await _search(q)
        for raw in raw_list:
            if not isinstance(raw, dict):
                continue
            parsed = _parse_notice(raw)
            if parsed:
                notices.append(parsed)

    deduped = _dedupe(notices)
    if deduped:
        logger.info(
            "Gazette: %d insolvency notice(s) for %r (canonical=%r, crn=%s)",
            len(deduped), company_name, canonical_name, crn,
        )
    return deduped


def has_hard_blocker(signals: list[GazetteSignal]) -> Optional[GazetteSignal]:
    """Return the first active signal that warrants a NO_GO, or None."""
    for s in signals:
        if s.active and s.notice_code in HARD_BLOCKER_CODES:
            return s
    return None
