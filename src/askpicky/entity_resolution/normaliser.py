"""Shared name-normalisation primitives.

Thin re-export of the helpers in `sub_agents.sponsor_register`. Keeping
the implementation there (where it grew up + is exercised by every
verdict) and exposing it under public names here so:
  - Companies House can reuse the same alias expansion
  - The front-page sponsor-search + visa-eligibility tools share the
    same surface-form space as the rest of the pipeline

If a primitive grows a new caller, this is the right place to host it
— do not fork.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from ..sub_agents.sponsor_register import (
    _ABBREVIATIONS,
    _LEGAL_SUFFIX_RE,
    _TRADING_AS_RE,
    _collapse,
    _discriminator_blocks_match,
    _ensemble_score,
    _expand_query_aliases,
    _is_identifier_token,
    _normalise,
    _strip_legal_suffix,
)


def normalise_name(name: str) -> str:
    """Lowercase, strip accents, drop punctuation, collapse whitespace."""
    return _normalise(name)


def strip_legal_suffix(name: str) -> str:
    """Iteratively strip trailing legal suffixes until stable."""
    return _strip_legal_suffix(name)


def expand_aliases(name: str) -> list[str]:
    """Generate canonical surface forms for a query.

    Symmetric with the sponsor-register row alias build — both sides
    live in the same surface-form space.
    """
    return _expand_query_aliases(name)


def discriminator_blocks_match(query: str, candidate: str) -> bool:
    """True when query + candidate differ ONLY by identifier tokens
    (digits, cardinals, Roman numerals, single letters). Sibling entities."""
    return _discriminator_blocks_match(query, candidate)


def ensemble_score(query: str, candidate: str) -> tuple[float, dict[str, float]]:
    """3-scorer rapidfuzz ensemble. Returns (combined_score, per-scorer breakdown)."""
    return _ensemble_score(query, candidate)


def slugify(name: str) -> str:
    """Stable URL-safe slug for a name. Used as fallback identity key."""
    base = strip_legal_suffix(normalise_name(name)) or normalise_name(name)
    if not base:
        return "unknown"
    out = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return out[:80] or "unknown"


# Re-export the underscore names too so the existing sponsor_register call
# sites that import them keep working (they live in the same package now).
__all__ = [
    "normalise_name",
    "strip_legal_suffix",
    "expand_aliases",
    "discriminator_blocks_match",
    "ensemble_score",
    "slugify",
    # common historic suffixes:
    "_normalise",
    "_strip_legal_suffix",
    "_expand_query_aliases",
    "_discriminator_blocks_match",
    "_ensemble_score",
    "_is_identifier_token",
    "_collapse",
    "_TRADING_AS_RE",
    "_LEGAL_SUFFIX_RE",
    "_ABBREVIATIONS",
]
