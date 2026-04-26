"""ATS host detection + LLM-provider routing for cv_tailor.

PROCESS Entry 44 — multi-provider CV tailoring.

The user-supplied mapping (ATS name -> LLM provider) is the source of
truth. Detection works in two layers:

  1. URL-host pattern -> ATS name  (deterministic, free, no LLM)
  2. ATS name -> Provider          (the user's mapping, frozen)

Unknown hosts default to "anthropic" (CLAUDE.md Rule 7 — Phase 4
generators default to Opus 4.7 when we lack a routing signal).

Gated by `settings.enable_multi_provider_cv_tailor`. When False, every
CV generation routes to Anthropic (the project's pre-2026-04-26
default).
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse


Provider = Literal["anthropic", "openai", "cohere"]


# ATS name (verbatim from the user's mapping) -> provider.
# Crelate was originally mapped to Llama (via Together AI); reassigned
# to Anthropic on 2026-04-26 (PROCESS Entry 44 follow-up). Llama support
# has been removed entirely from the codebase — no adapter, no config,
# no smoke entry.
ATS_TO_PROVIDER: dict[str, Provider] = {
    "Workday Recruiting": "anthropic",
    "iCIMS": "openai",
    "Greenhouse": "openai",
    "SmartRecruiters": "anthropic",
    "SAP SuccessFactors": "openai",
    "Oracle Recruiting": "cohere",
    "ADP Recruiting": "anthropic",
    "Workable": "anthropic",
    "Teamtailor": "openai",
    "Pinpoint": "openai",
    "Eploy": "openai",
    "Recruitee": "openai",
    "BambooHR": "cohere",
    "Bullhorn": "openai",
    "JobAdder": "anthropic",
    "Zoho Recruit": "openai",
    "Recruiterflow": "openai",
    "Firefish": "openai",
    "Tribepad": "anthropic",
    "Jobtrain": "openai",
    "PeopleHR": "openai",
    "Lever": "anthropic",
    "Crelate": "anthropic",
    "Oracle Cloud HCM": "cohere",
    "SAP SuccessFactors Recruiting": "openai",
}


# Each entry: (host_substring, ATS name in ATS_TO_PROVIDER).
# Matched via right-anchored host suffix OR substring (ATS hosts are
# stable and distinctive — no need for full regex). Order matters when
# two patterns could match (more-specific first).
_HOST_PATTERNS: list[tuple[str, str]] = [
    # Workday — myworkdayjobs.com is the public-careers host.
    ("myworkdayjobs.com", "Workday Recruiting"),
    ("workday.com", "Workday Recruiting"),
    # iCIMS
    ("icims.com", "iCIMS"),
    # Greenhouse
    ("boards.greenhouse.io", "Greenhouse"),
    ("greenhouse.io", "Greenhouse"),
    # SmartRecruiters
    ("smartrecruiters.com", "SmartRecruiters"),
    # SAP SuccessFactors — multiple host shapes
    ("successfactors.com", "SAP SuccessFactors"),
    ("sapsf.com", "SAP SuccessFactors"),
    ("sapsf.eu", "SAP SuccessFactors"),
    # Oracle Recruiting / Cloud HCM — distinguish by host
    ("oraclecloud.com", "Oracle Cloud HCM"),
    ("taleo.net", "Oracle Recruiting"),
    ("oracle.com", "Oracle Recruiting"),
    # ADP
    ("workforcenow.adp.com", "ADP Recruiting"),
    ("adp.com", "ADP Recruiting"),
    # Workable
    ("apply.workable.com", "Workable"),
    ("workable.com", "Workable"),
    # Teamtailor
    ("teamtailor.com", "Teamtailor"),
    # Pinpoint
    ("pinpointhq.com", "Pinpoint"),
    # Eploy (UK)
    ("eploy.co.uk", "Eploy"),
    ("eploy.com", "Eploy"),
    # Recruitee
    ("recruitee.com", "Recruitee"),
    # BambooHR
    ("bamboohr.com", "BambooHR"),
    # Bullhorn
    ("bullhornstaffing.com", "Bullhorn"),
    ("bullhorn.com", "Bullhorn"),
    # JobAdder
    ("jobadder.com", "JobAdder"),
    # Zoho Recruit
    ("zohorecruit.com", "Zoho Recruit"),
    ("recruit.zoho.com", "Zoho Recruit"),
    # Recruiterflow
    ("recruiterflow.com", "Recruiterflow"),
    # Firefish (UK)
    ("firefishsoftware.com", "Firefish"),
    # Tribepad (UK)
    ("tribepad.com", "Tribepad"),
    # Jobtrain (UK)
    ("jobtrain.co.uk", "Jobtrain"),
    # PeopleHR (UK)
    ("peoplehr.net", "PeopleHR"),
    ("peoplehr.com", "PeopleHR"),
    # Lever
    ("jobs.lever.co", "Lever"),
    ("lever.co", "Lever"),
    # Crelate
    ("crelate.com", "Crelate"),
    # SAP SuccessFactors Recruiting (when we can distinguish a Recruiting-
    # specific subdomain). Same host roots as SuccessFactors, so this
    # branch is for explicit overrides only.
]


def detect_ats_name(job_url: str) -> str | None:
    """Return the ATS display name (matching ATS_TO_PROVIDER keys), or
    None for hosts not covered by the routing table.
    """
    if not job_url:
        return None
    host = (urlparse(job_url).hostname or "").lower()
    if not host:
        return None
    for pattern, ats_name in _HOST_PATTERNS:
        if host.endswith(pattern) or pattern in host:
            return ats_name
    return None


def provider_for_url(job_url: str, *, default: Provider = "anthropic") -> Provider:
    """Return the provider this URL routes to, per the ATS_TO_PROVIDER
    mapping. Unknown ATS hosts -> `default` (Anthropic — preserves the
    project's pre-2026-04-26 behaviour for everything outside the
    mapping)."""
    ats = detect_ats_name(job_url)
    if ats is None:
        return default
    return ATS_TO_PROVIDER.get(ats, default)


def explain_route(job_url: str) -> dict:
    """Diagnostic — returns the routing trace for a URL.

    Useful for /sessions/{id} debug payloads and smoke-test logs.
    """
    ats = detect_ats_name(job_url)
    return {
        "job_url": job_url,
        "host": (urlparse(job_url).hostname or "").lower() if job_url else None,
        "ats_name": ats,
        "provider": ATS_TO_PROVIDER.get(ats, "anthropic") if ats else "anthropic",
        "is_default": ats is None,
    }
