"""Phase 1 — Companies House lookup.

Free official API: https://developer.company-information.service.gov.uk/
Auth: HTTP basic auth, username = api_key, password = empty.

No LLM involved. Pure data retrieval.

Resolution path:
  - If the caller already has a CRN (typically from
    `entity_resolution.resolve_company_identity`), skip search and
    fetch the profile directly. This is the high-confidence path —
    no fuzzy match risk.
  - Otherwise fall back to search, but score every hit against the
    input + (optionally) any sponsor-anchored alias the resolver
    gave us. NEVER pick `items[0]` blindly — that's the silent-
    false-positive failure mode the unified resolver fixes.
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


async def _officers(company_number: str) -> list[dict]:
    """`/company/{number}/officers` — directors, secretaries, etc.

    Returns each officer's `appointed_on` + `resigned_on` (None if
    still active). 6-month-window counts of resignations and new
    appointments are computed by the caller.
    """
    async with await _client() as client:
        resp = await client.get(
            f"/company/{company_number}/officers",
            params={"items_per_page": 50},
        )
        if resp.status_code != 200:
            return []
        return resp.json().get("items", [])


async def _charges(company_number: str) -> list[dict]:
    """`/company/{number}/charges` — registered debt/mortgages.

    A sudden flurry of new charges in the last 6 months is a known
    pre-failure liquidity-scramble signal: the company is securing
    cash against its remaining assets to keep going.
    """
    async with await _client() as client:
        resp = await client.get(
            f"/company/{company_number}/charges",
            params={"items_per_page": 50},
        )
        if resp.status_code != 200:
            return []
        return resp.json().get("items", [])


async def _psc(company_number: str) -> list[dict]:
    """`/company/{number}/persons-with-significant-control`.

    PSC changes (ownership turning over fast) flag ownership-side
    restructuring — sometimes precedes the company being sold or
    the parent company going under.
    """
    async with await _client() as client:
        resp = await client.get(
            f"/company/{company_number}/persons-with-significant-control",
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


def _within_last_n_months(d: Optional[date], months: int = 6) -> bool:
    if d is None:
        return False
    today = date.today()
    return (today - d).days <= months * 30


def _count_recent_director_changes(
    officers: list[dict],
) -> tuple[int, int]:
    """Returns (resignations_6mo, appointments_6mo).

    Officer payloads carry `appointed_on` and `resigned_on` ISO dates.
    We count resignations from the resigned date and new appointments
    from the appointed date. Both windows are last 6 months.
    """
    resigned = 0
    appointed = 0
    for o in officers:
        # Officer type filter — count directors + secretaries; skip
        # nominee / LLP-member roles that don't carry the same signal.
        role = (o.get("officer_role") or "").lower()
        if "director" not in role and "secretary" not in role:
            continue
        if _within_last_n_months(_parse_date(o.get("resigned_on"))):
            resigned += 1
        if _within_last_n_months(_parse_date(o.get("appointed_on"))):
            appointed += 1
    return resigned, appointed


def _count_recent_charges(charges: list[dict]) -> int:
    """Count debt/mortgage charges registered in the last 6 months."""
    return sum(
        1 for c in charges
        if _within_last_n_months(_parse_date(c.get("delivered_on")))
    )


def _count_recent_psc_changes(psc_items: list[dict]) -> int:
    """Count PSCs whose `notified_on` or `ceased_on` fell in the last 6 months.

    Either signal means ownership churned recently.
    """
    count = 0
    for p in psc_items:
        if _within_last_n_months(_parse_date(p.get("notified_on"))):
            count += 1
        elif _within_last_n_months(_parse_date(p.get("ceased_on"))):
            count += 1
    return count


def _extract_corporate_parents(psc_items: list[dict]) -> list[dict]:
    """Pull corporate (non-individual) PSCs out of the raw PSC items.

    When the JD's company is a subsidiary, the Sponsor Register lookup against
    that exact name can return NOT_LISTED while the parent is on the register.
    We return one row per corporate parent for the orchestrator's parent-walk
    step.

    Filters:
      - Only `kind in {corporate-entity-person-with-significant-control,
        legal-person-person-with-significant-control}` — skip individuals.
      - Skip parents whose `ceased_on` is set.
      - Deduplicate by name.

    Returns dicts of {name, crn, kind}. Caller wraps in ParentCompany.
    """
    _CORPORATE_KINDS = {
        "corporate-entity-person-with-significant-control",
        "legal-person-person-with-significant-control",
    }
    seen: set[str] = set()
    out: list[dict] = []
    for p in psc_items:
        kind = (p.get("kind") or "").lower()
        if kind not in _CORPORATE_KINDS:
            continue
        if p.get("ceased_on"):
            continue
        name = (p.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        ident = p.get("identification") or {}
        crn = ident.get("registration_number") or None
        out.append({"name": name, "crn": str(crn) if crn else None, "kind": kind})
    return out


def _pick_best_search_hit(
    query: str,
    hits: list[dict],
    *,
    aliases: Optional[list[str]] = None,
    accept_threshold: float = 80.0,
) -> Optional[str]:
    """Score every CH search hit, return the best CRN above threshold.

    Uses the same rapidfuzz ensemble as the sponsor matcher so scoring is
    consistent across the pipeline. Falls back to `items[0]`'s CRN when no hit
    clears the threshold so the caller can inspect a low-confidence candidate.
    """
    # Imported here so this module stays importable when the
    # entity_resolution package isn't on path (e.g. partial deploy).
    try:
        from ..entity_resolution.normaliser import ensemble_score
    except Exception:
        # Pure fallback if the resolver module isn't available.
        first = hits[0] if hits else {}
        return first.get("company_number")

    anchors = [query]
    if aliases:
        anchors.extend(a for a in aliases if a)

    best_score = -1.0
    best_crn: Optional[str] = None
    for hit in hits:
        candidate = hit.get("title") or ""
        if not candidate:
            continue
        # Best score across all anchors — sponsor-anchored aliases give
        # the resolver a second shot if the raw query is too casual.
        score = max(
            ensemble_score(anchor, candidate)[0] for anchor in anchors
        )
        if score > best_score:
            best_score = score
            best_crn = hit.get("company_number")

    if best_crn and best_score >= accept_threshold:
        return best_crn
    # Soft fallback: even below threshold, return the top hit so the
    # caller has *something* to verify against — but they should treat
    # the result as low-confidence.
    return hits[0].get("company_number") if hits else None


async def lookup(
    company_name: str,
    *,
    crn: Optional[str] = None,
    aliases: Optional[list[str]] = None,
) -> Optional[CompaniesHouseSnapshot]:
    """Return a snapshot for the best-matching Companies House entry.

    Resolver-anchored path (preferred): when `crn` is supplied (from
    `entity_resolution.resolve_company_identity`), skip search and
    fetch the profile + filings directly. Returns None on missing key
    or unreachable API.

    Name-search path (`crn=None`): search and score every hit against the
    input. The `aliases` argument lets the resolver pass in sponsor-anchored
    canonical forms ("Octopus Energy Limited" when the JD says "Octopus") so
    scoring has a second anchor.
    """
    if not settings.companies_house_api_key:
        logger.info("Companies House API key not set; skipping lookup.")
        return None

    company_number = crn
    if not company_number:
        try:
            items = await _search(company_name)
        except Exception as e:
            logger.warning("Companies House search failed for %r: %s", company_name, e)
            return None
        if not items:
            return None
        company_number = _pick_best_search_hit(
            company_name, items, aliases=aliases,
        )
        if not company_number:
            return None

    try:
        profile = await _profile(company_number)
    except Exception as e:
        logger.warning("Companies House profile fetch failed: %s", e)
        return None
    if not profile:
        return None

    # Pull filings + officers + charges + PSC in parallel. Each
    # endpoint is independent at the API level, so async-gather is a
    # free win versus the previous serial pulls.
    import asyncio as _asyncio
    filings, officers, charges, psc_items = await _asyncio.gather(
        _filings(company_number),
        _officers(company_number),
        _charges(company_number),
        _psc(company_number),
        return_exceptions=True,
    )
    # asyncio.gather with return_exceptions=True swallows individual
    # failures into the result list — coerce each back to [] so the
    # downstream counters never see an exception object.
    if isinstance(filings, Exception):
        filings = []
    if isinstance(officers, Exception):
        officers = []
    if isinstance(charges, Exception):
        charges = []
    if isinstance(psc_items, Exception):
        psc_items = []

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

    resignations_6mo, appointments_6mo = _count_recent_director_changes(officers)
    charges_6mo = _count_recent_charges(charges)
    psc_6mo = _count_recent_psc_changes(psc_items)
    corporate_parents = _extract_corporate_parents(psc_items)

    from ..schemas import ParentCompany

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
        recent_director_resignations_6mo=resignations_6mo,
        recent_director_appointments_6mo=appointments_6mo,
        recent_charges_6mo=charges_6mo,
        psc_changes_6mo=psc_6mo,
        parent_companies=[ParentCompany(**p) for p in corporate_parents],
    )
