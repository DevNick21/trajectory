"""Unified company identity resolution.

One canonical name + CRN per real-world employer, derived from:
  - the raw name extracted from the JD / scraper
  - the Home Office Sponsor Register (parquet, fuzzy + Splink-rescored)
  - Companies House (live search → top-K → ensemble-scored → CRN)

Downstream consumers (sponsor_register.lookup, companies_house.lookup,
the visa-eligibility + sponsor-search front-page tools) take a
`CompanyIdentity` instead of a raw string. When a CRN is anchored,
sponsor + CH lookups skip the fuzzy step and join on CRN directly —
that's the failure mode this module fixes.

Cache by CRN (preferred) or by normalised name slug (fallback when no
CRN can be anchored). Cached rows live in the `company_identities`
SQLite table; misses trigger a fresh resolve.
"""

from .schemas import CompanyIdentity, ResolutionTrace
from .resolver import resolve_company_identity

__all__ = [
    "CompanyIdentity",
    "ResolutionTrace",
    "resolve_company_identity",
]
