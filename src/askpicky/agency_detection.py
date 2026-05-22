"""Deterministic recruitment-agency post detector.

Architecture gap #5 — JD extractor returns one `company_name`, but
that name is often the *agency* (Hays, Robert Walters, Michael Page,
…) rather than the actual hiring entity. The downstream Sponsor
Register / Companies House lookups then run against the agency, not
the employer — a false NOT_LISTED for visa users, or a confident
GO on a company that isn't actually the one hiring.

This module flags the *posting* as an agency post so the verdict
agent can soften its position. It does NOT try to re-resolve the
actual client — that requires the JD body to name the client, which
is the exception not the rule.

Pattern: zero LLM, ~0.5ms, runs after JD extraction. Returns:
  - is_agency_post: bool
  - agency_client_name: Optional[str] — None when the client is
    anonymised
  - agency_signals: list[str] — which phrases / heuristics fired,
    for verdict citation discipline
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# Strong phrases — ANY one of these flips is_agency_post to True on
# its own. These are unambiguous in agency JDs and don't appear in
# in-house HR copy without contortion.
_STRONG_PHRASES = [
    r"\bon behalf of (?:our|the|a)\s+client\b",
    r"\brecruiting on behalf of\b",
    r"\b(?:our|the)\s+client\s+(?:is|are)\s+(?:seeking|looking|hiring|recruiting)\b",
    r"\binterviews?\s+will be\s+conducted by (?:our|the)\s+client\b",
    r"\bworking exclusively with (?:our|the|a)\s+client\b",
    r"\bsearching on behalf of\b",
]

# Weak phrases — need 2+ of these together, OR 1 + agency-name signal,
# to flip. Each on its own is ambiguous ("our client" appears in
# consultancy JDs that aren't agency posts).
_WEAK_PHRASES = [
    r"\b(?:our|the)\s+client\b",
    r"\bclient(?:'s)?\s+(?:company|business|organisation|firm)\b",
    r"\b(?:send|email)\s+your\s+(?:cv|resume)\s+to\b",
    r"\bsuccessful candidates?\s+will be\s+forwarded\b",
    r"\bpre[\s-]?screen(?:ing)?\s+(?:by|via)\s+us\b",
]

# Known UK recruitment agency name fragments. Case-insensitive whole-
# word match against the extracted company_name. Not exhaustive — the
# point is to add weight, not to identify the agency.
_AGENCY_NAME_FRAGMENTS = {
    "hays", "reed", "robert walters", "michael page", "pagegroup",
    "adecco", "manpower", "randstad", "sthree", "hudson",
    "frank recruitment", "search consultancy", "aston carter",
    "harvey nash", "spring", "goodman masson", "morson", "lorien",
    "computer futures", "huxley", "real staffing", "progressive recruitment",
    "oliver bonas recruitment",  # placeholder — fill from a real source
    "alexander mann", "blackwood", "venturi", "investigo",
    "nigel frank", "tenth revolution", "harnham",
}

# Patterns that attempt to extract the client name when the agency
# reveals it. Capture group #1 is the client name.
_CLIENT_NAME_PATTERNS = [
    re.compile(
        r"(?:our|the)\s+client[,]?\s+([A-Z][A-Za-z0-9 &\.\-']{2,60}?)[,\.]",
    ),
    re.compile(
        r"(?:on behalf of|recruiting for)\s+([A-Z][A-Za-z0-9 &\.\-']{2,60}?)[,\.]",
    ),
    re.compile(
        r"client[,]?\s+([A-Z][A-Z0-9 &\.\-']{2,60})\s+(?:Limited|Ltd|PLC|LLP)",
    ),
]


@dataclass(frozen=True)
class AgencyDetectionResult:
    is_agency_post: bool
    agency_client_name: Optional[str] = None
    agency_signals: list[str] = field(default_factory=list)


def _agency_name_in_company(company_name: Optional[str]) -> Optional[str]:
    if not company_name:
        return None
    lowered = company_name.lower()
    for frag in _AGENCY_NAME_FRAGMENTS:
        if re.search(r"\b" + re.escape(frag) + r"\b", lowered):
            return frag
    return None


def _extract_client_name(jd_text: str) -> Optional[str]:
    head = jd_text[:4000]
    for pattern in _CLIENT_NAME_PATTERNS:
        match = pattern.search(head)
        if match:
            name = re.sub(r"\s+", " ", match.group(1)).strip()
            if 3 <= len(name) <= 60 and name.lower() not in {
                "our client", "the client", "client",
            }:
                return name
    return None


def detect_agency_post(
    jd_text: str,
    *,
    company_name: Optional[str] = None,
) -> AgencyDetectionResult:
    """Classify a JD body + extracted company name as an agency post.

    Decision rule:
      - 1+ strong phrase  → agency_post (high precision)
      - 2+ weak phrases   → agency_post
      - 1 weak phrase + known agency company_name → agency_post
      - known agency company_name alone → agency_post (low-recall
        but the agency name itself is the strongest single signal)
      - otherwise         → not agency_post
    """
    if not jd_text:
        return AgencyDetectionResult(is_agency_post=False)

    text = jd_text.lower()
    signals: list[str] = []

    strong_hits = [
        p for p in _STRONG_PHRASES
        if re.search(p, text, re.IGNORECASE)
    ]
    weak_hits = [
        p for p in _WEAK_PHRASES
        if re.search(p, text, re.IGNORECASE)
    ]
    agency_name = _agency_name_in_company(company_name)

    is_agency = False
    if strong_hits:
        is_agency = True
        signals.extend(f"strong_phrase:{p}" for p in strong_hits)
    elif len(weak_hits) >= 2:
        is_agency = True
        signals.extend(f"weak_phrase:{p}" for p in weak_hits)
    elif weak_hits and agency_name:
        is_agency = True
        signals.append(f"agency_name:{agency_name}")
        signals.extend(f"weak_phrase:{p}" for p in weak_hits)
    elif agency_name:
        is_agency = True
        signals.append(f"agency_name:{agency_name}")

    client_name = _extract_client_name(jd_text) if is_agency else None

    return AgencyDetectionResult(
        is_agency_post=is_agency,
        agency_client_name=client_name,
        agency_signals=signals,
    )
