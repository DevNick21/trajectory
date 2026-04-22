"""Phase 1 — Companies House lookup.

Free official API: https://developer.company-information.service.gov.uk/
Auth: HTTP basic auth, username = api_key, password = empty.

No LLM involved. Pure data retrieval.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import httpx

from ..config import settings
from ..schemas import CompaniesHouseSnapshot

logger = logging.getLogger(__name__)


_BASE = "https://api.company-information.service.gov.uk"
_TIMEOUT = 15.0


_STATUS_MAP = {
    "active": "ACTIVE",
    "dissolved": "DISSOLVED",
    "administration": "IN_ADMINISTRATION",
    "liquidation": "IN_LIQUIDATION",
    "receivership": "IN_LIQUIDATION",
    "voluntary-arrangement": "IN_LIQUIDATION",
    "open": "ACTIVE",
    "converted-closed": "ACTIVE_CONVERSION",
}


def _map_status(raw: Optional[str]) -> str:
    if not raw:
        return "OTHER"
    return _STATUS_MAP.get(raw.lower(), "OTHER")


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


async def _client() -> httpx.AsyncClient:
    if not settings.companies_house_api_key:
        raise RuntimeError("COMPANIES_HOUSE_API_KEY not configured")
    return httpx.AsyncClient(
        base_url=_BASE,
        auth=(settings.companies_house_api_key, ""),
        timeout=_TIMEOUT,
    )


async def _search(name: str) -> list[dict]:
    async with await _client() as client:
        resp = await client.get("/search/companies", params={"q": name, "items_per_page": 5})
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("items", [])


async def _profile(company_number: str) -> Optional[dict]:
    async with await _client() as client:
        resp = await client.get(f"/company/{company_number}")
        if resp.status_code != 200:
            return None
        return resp.json()


async def _filings(company_number: str) -> list[dict]:
    async with await _client() as client:
        resp = await client.get(
            f"/company/{company_number}/filing-history",
            params={"items_per_page": 50},
        )
        if resp.status_code != 200:
            return []
        return resp.json().get("items", [])


def _years_since(d: Optional[date]) -> int:
    if d is None:
        return 99
    today = date.today()
    return (today - d).days // 365


async def lookup(company_name: str) -> Optional[CompaniesHouseSnapshot]:
    """Return a snapshot for the best-matching Companies House entry.

    Returns None if API not configured or no plausible match. The verdict
    agent treats None as "could not verify" — not a hard blocker.
    """
    if not settings.companies_house_api_key:
        logger.info("Companies House API key not set; skipping lookup.")
        return None

    try:
        items = await _search(company_name)
    except Exception as e:
        logger.warning("Companies House search failed for %r: %s", company_name, e)
        return None

    if not items:
        return None

    top = items[0]
    company_number = top.get("company_number")
    if not company_number:
        return None

    try:
        profile = await _profile(company_number)
    except Exception as e:
        logger.warning("Companies House profile fetch failed: %s", e)
        return None
    if not profile:
        return None

    try:
        filings = await _filings(company_number)
    except Exception:
        filings = []

    accounts = profile.get("accounts", {}) or {}
    confirmation = profile.get("confirmation_statement", {}) or {}
    last_accounts = accounts.get("last_accounts", {}) or {}
    last_accounts_date = _parse_date(last_accounts.get("made_up_to"))

    last_filing_dates = [
        _parse_date(f.get("date")) for f in filings if f.get("date")
    ]
    last_filing_dates = [d for d in last_filing_dates if d]
    most_recent = max(last_filing_dates) if last_filing_dates else None

    resolution_to_wind_up = any(
        "WIND" in (f.get("description") or "").upper()
        or "WIND" in (f.get("subcategory") or "").upper()
        for f in filings
    )

    return CompaniesHouseSnapshot(
        company_number=company_number,
        status=_map_status(profile.get("company_status")),
        company_name_official=profile.get("company_name", company_name),
        sic_codes=list(profile.get("sic_codes") or []),
        incorporation_date=_parse_date(profile.get("date_of_creation")),
        accounts_overdue=bool(accounts.get("overdue", False)),
        confirmation_statement_overdue=bool(confirmation.get("overdue", False)),
        last_accounts_date=last_accounts_date,
        no_filings_in_years=_years_since(most_recent),
        resolution_to_wind_up=resolution_to_wind_up,
        director_disqualifications=0,  # Requires a separate endpoint; skeleton skips.
    )
