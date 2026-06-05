"""Local Companies House name index — replaces /search/companies.

Loads the slim parquet produced by `scripts/fetch_ch_bulk.py` into a
blocked + aliased index, then exposes `search_by_name(query)` returning
candidate hits in the same shape the rate-limited API does. The
resolver picks this path ahead of the API when the parquet exists.

Indexing mirrors the sponsor-register matcher: first-token block +
4-character-prefix block over an alias pool that includes the canonical
CompanyName + each PreviousName. Lookup runs the same rapidfuzz
ensemble.

Why this matters operationally:
  - No rate limit. The bulk product is one monthly download.
  - Previous-name coverage. The CSV has up to 10 historic names per
    company, so rebrand-tolerant matching is free.
  - Faster — ~200-1000 candidates blocked from 5M rows per query, all
    in-process.
  - Open-data path. Fits the project's first-party-only stance.

ADR 0017 in kanu makes the same trade-off (retire the API name path).
The /company/{number} live API endpoint is still used by
`companies_house.lookup` for fresh status + filings once we have a CRN.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..config import settings
from .normaliser import (
    _strip_legal_suffix as strip_legal_suffix,
    discriminator_blocks_match,
    ensemble_score,
    expand_aliases,
    normalise_name,
)

logger = logging.getLogger(__name__)


# Score floor for accepting a local-index hit. Set high — the rest of
# the resolver pipeline can fall through to the API if no local hit
# clears this. Empirically the sponsor-register matcher uses ~92 on
# the same scorer ensemble; we keep parity.
LOCAL_ACCEPT_THRESHOLD = 88.0

# Top-K candidates returned per query. The resolver scores them against
# the input + sponsor-anchored aliases (if any) and picks the best.
TOP_K = 5


# Stop-tokens that don't help disambiguate companies. Indexing on these
# would surface most of the register as a candidate (thousands of "the X
# limited" / "we Y group" rows). Keeping them out of the multi-token
# block keeps blocking selective.
_BLOCK_STOP_TOKENS = frozenset({
    "the", "a", "an", "we", "our", "of", "and", "or", "for",
    "ltd", "ltd.", "limited", "plc", "llp", "llc", "lp", "inc",
    "co", "co.", "company", "group", "holdings", "services",
    "uk", "gb", "international", "intl", "global",
})


@dataclass
class _CHIndex:
    df: object  # pandas DataFrame
    aliases: list[tuple[str, int]] = field(default_factory=list)
    first_token_block: dict[str, list[int]] = field(default_factory=dict)
    prefix4_block: dict[str, list[int]] = field(default_factory=dict)
    # Multi-token block: alias indexed under EVERY significant token,
    # not just the first. Fixes the "WE LOVE HOLIDAYS LIMITED" miss
    # where the brand is "loveholidays" but the first token of the
    # legal name is "we" — pure first-token blocking never considered it.
    token_block: dict[str, list[int]] = field(default_factory=dict)


_index: Optional[_CHIndex] = None
_index_lock = threading.Lock()


def parquet_path() -> Path:
    return settings.data_dir / "processed" / "ch_companies.parquet"


def index_available() -> bool:
    return parquet_path().exists()


def _build_index_from_df(df) -> _CHIndex:
    idx = _CHIndex(df=df)
    seen: set[tuple[str, int]] = set()

    def add(alias_raw: str, row_idx: int) -> None:
        alias = normalise_name(alias_raw)
        if not alias:
            return
        key = (alias, row_idx)
        if key in seen:
            return
        seen.add(key)
        alias_idx = len(idx.aliases)
        idx.aliases.append((alias, row_idx))
        first_token = alias.split(" ", 1)[0]
        idx.first_token_block.setdefault(first_token, []).append(alias_idx)
        idx.prefix4_block.setdefault(alias[:4], []).append(alias_idx)
        # Multi-token block — every significant token. Fixes brand-
        # buried-in-legal-name misses (e.g. "we love holidays" vs
        # "loveholidays").
        for tok in alias.split():
            if len(tok) >= 3 and tok not in _BLOCK_STOP_TOKENS:
                idx.token_block.setdefault(tok, []).append(alias_idx)

    company_names = df["CompanyName"].astype(str).tolist()
    previous_names_blob = (
        df["PreviousNames"].astype(str).tolist()
        if "PreviousNames" in df.columns else None
    )
    for row_idx, name in enumerate(company_names):
        add(name, row_idx)
        bare = strip_legal_suffix(normalise_name(name))
        if bare and bare != normalise_name(name):
            add(bare, row_idx)
        if previous_names_blob:
            try:
                prev = json.loads(previous_names_blob[row_idx] or "[]")
            except json.JSONDecodeError:
                prev = []
            for p in prev:
                add(p, row_idx)
    return idx


def _load_index() -> Optional[_CHIndex]:
    """Lazy-load. Returns None if the parquet is missing."""
    global _index
    if _index is not None:
        return _index
    with _index_lock:
        if _index is not None:
            return _index
        p = parquet_path()
        if not p.exists():
            return None
        try:
            import pandas as pd
            df = pd.read_parquet(p)
        except Exception as exc:
            logger.warning("Failed to load CH parquet at %s: %s", p, exc)
            return None
        logger.info(
            "Loading CH local index: %s rows from %s", len(df), p,
        )
        _index = _build_index_from_df(df)
        logger.info(
            "Index ready: %d aliases, %d first-token blocks, %d prefix4 blocks",
            len(_index.aliases),
            len(_index.first_token_block),
            len(_index.prefix4_block),
        )
        return _index


def _block_alias_indices(
    query_aliases: list[str], idx: _CHIndex,
) -> set[int]:
    """Return alias-pool indices (not row indices) to score against.

    Three blocking strategies pooled:
      - First-token block (anchors short queries)
      - 4-char-prefix block (catches typos / casing variants)
      - Multi-token block (covers brand-buried-in-legal-name e.g.
        "loveholidays" -> "we love holidays limited")

    Returning alias indices instead of row indices lets the scorer
    compare the query against the *matched* alias (e.g. a previous
    name like 'TRANSFERWISE LTD') rather than the canonical name
    (e.g. 'WISE PAYMENTS LIMITED').
    """
    alias_ids: set[int] = set()
    for alias in query_aliases:
        if not alias:
            continue
        first_token = alias.split(" ", 1)[0]
        alias_ids.update(idx.first_token_block.get(first_token, []))
        alias_ids.update(idx.prefix4_block.get(alias[:4], []))
        # Multi-token block — every alias contributes its significant
        # tokens. Solves the loveholidays misfire from 2026-05-22.
        for tok in alias.split():
            if len(tok) >= 3 and tok not in _BLOCK_STOP_TOKENS:
                alias_ids.update(idx.token_block.get(tok, []))
    return alias_ids


@dataclass
class LocalCHHit:
    """One CH match — shaped to mirror the /search/companies item dict."""

    company_number: str
    company_name: str
    company_status: Optional[str]
    incorporation_date: Optional[str]  # YYYY-MM-DD from the parquet
    score: float
    matched_alias: str  # which alias variant matched (canonical or a previous name)

    def as_search_item(self) -> dict:
        """Render as the legacy /search/companies item shape."""
        item: dict = {
            "company_number": self.company_number,
            "title": self.company_name,
            "company_status": (self.company_status or "").lower() or None,
            "date_of_creation": self.incorporation_date,
        }
        return item


def search_by_name(
    query: str, *, top_k: int = TOP_K, threshold: float = LOCAL_ACCEPT_THRESHOLD,
) -> list[LocalCHHit]:
    """Return up to top_k LocalCHHit ranked by ensemble score (desc).

    Empty list when the parquet is missing, no candidates clear blocking,
    or no scored candidate clears `threshold`. Caller should fall back
    to the rate-limited API in that case.
    """
    idx = _load_index()
    if idx is None or not query:
        return []
    aliases = expand_aliases(query)
    if not aliases:
        return []
    alias_ids = _block_alias_indices(aliases, idx)
    if not alias_ids:
        return []

    df = idx.df
    company_names = df["CompanyName"]
    company_numbers = df["CompanyNumber"]
    statuses = df["CompanyStatus"] if "CompanyStatus" in df.columns else None
    inc_dates = df["IncorporationDate"] if "IncorporationDate" in df.columns else None

    # Score each blocked alias against the query, then keep the best
    # score per row. Previous-name matches surface here because we
    # compare against the matched alias text (e.g. "TRANSFERWISE LTD")
    # not the canonical name (e.g. "WISE PAYMENTS LIMITED").
    best_by_row: dict[int, LocalCHHit] = {}
    for alias_idx in alias_ids:
        alias_text, row_idx = idx.aliases[alias_idx]
        canonical = str(company_names.iloc[row_idx])
        if not canonical:
            continue
        # Discriminator veto on the CANONICAL name only — sibling-row
        # vetoes (SPV #4 vs SPV #18) shouldn't fire for a rebrand
        # match. Run it on the canonical form to keep parity with the
        # sponsor matcher.
        if discriminator_blocks_match(query, canonical):
            continue
        combined, _ = ensemble_score(query, alias_text)
        if combined < threshold:
            continue
        crn = str(company_numbers.iloc[row_idx])
        status = str(statuses.iloc[row_idx]) if statuses is not None else None
        inc_date: Optional[str] = None
        if inc_dates is not None:
            raw_date = inc_dates.iloc[row_idx]
            if hasattr(raw_date, "strftime"):
                formatted = raw_date.strftime("%Y-%m-%d")
                if formatted != "NaT":
                    inc_date = formatted
            elif isinstance(raw_date, str) and raw_date.strip():
                inc_date = raw_date.strip()[:10]
        existing = best_by_row.get(row_idx)
        if existing is None or combined > existing.score:
            best_by_row[row_idx] = LocalCHHit(
                company_number=crn,
                company_name=canonical,
                company_status=status,
                incorporation_date=inc_date,
                score=combined,
                matched_alias=alias_text,
            )

    scored = sorted(best_by_row.values(), key=lambda h: h.score, reverse=True)
    return scored[:top_k]


def reload_index() -> None:
    """Force the next lookup to rebuild from disk. Test hook."""
    global _index
    with _index_lock:
        _index = None
