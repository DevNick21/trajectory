"""Pydantic schemas for unified company-identity resolution."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# How confident the resolver is that this identity matches the input.
# Anchored on CRN = 1.0. Pure name match in the ambiguous band = ~0.7.
# Unverified (raw input only, no external anchor) = 0.0.
ResolutionConfidence = float


class ResolutionTrace(BaseModel):
    """Debugging breadcrumb — why the resolver picked this identity."""

    raw_input: str
    aliases_tried: list[str] = Field(default_factory=list)
    candidates_considered: int = 0
    chosen_score: Optional[float] = None
    chosen_via: Literal[
        "cache_hit_crn",
        "cache_hit_slug",
        "crn_hint",
        "companies_house_search",
        "sponsor_register_search",
        "fallback_raw",
    ] = "fallback_raw"
    splink_rescored: bool = False


class CompanyIdentity(BaseModel):
    """One real-world employer, unified across data sources.

    `identity_id` is the canonical key downstream code joins on:
      - `crn:12345678` when a Companies House Registration Number was
        anchored (the preferred case — CH is the universe of UK companies).
      - `name:<normalised-slug>` when no CRN could be anchored
        (recruitment-agency posts, very small employers, etc.).

    A thin identity (`confidence < 0.5`, no CRN) is still useful — it
    gives downstream code a stable id to cache against and a list of
    aliases to try on retries.
    """

    identity_id: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    legal_names: list[str] = Field(default_factory=list)
    trading_names: list[str] = Field(default_factory=list)

    crn: Optional[str] = None
    company_status: Optional[str] = None  # CH status when known
    sponsor_register_name: Optional[str] = None
    sponsor_status: Optional[str] = None  # LISTED / B_RATED / SUSPENDED / NOT_LISTED / UNKNOWN
    sponsor_match_confidence: Optional[float] = None
    parent_crn: Optional[str] = None
    domain: Optional[str] = None

    confidence: ResolutionConfidence = 0.0
    sources: list[str] = Field(default_factory=list)
    trace: Optional[ResolutionTrace] = None

    resolved_at: datetime
