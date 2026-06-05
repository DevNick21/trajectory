"""Phase 1 — Sponsor Register lookup with multi-signal matching.

Block-then-score pipeline:

1. **Query alias expansion.** The query is normalised, suffix-stripped,
   trade-name-split, abbreviation-swapped, and `& ↔ and` expanded.
   Mirrors the alias generation already done for register rows so
   query- and register-side variants live in the same surface-form space.

2. **Blocking before scoring.** A first-token and 4-character-prefix
   index narrows the ~141k-row register to ~10-1000 candidates per
   query alias. `process.extractOne` previously scanned all aliases
   linearly per call — fine for one verdict, expensive for batch/queue.

3. **Multi-scorer ensemble.** Combines `WRatio`, `token_sort_ratio`,
   and `partial_ratio`. The combined score is the min of WRatio and
   token_sort_ratio, optionally penalised when partial_ratio diverges.
   Three orthogonal signals separate "Octopus Energy" vs
   "Octopus Energy Limited" (high on all three) from "Wise" vs
   "Aaron Wise Limited" (high partial, low token_sort).

4. **Discriminator-token veto.** Ported from kanu's
   `resolution.extractor._discriminator_blocks_merge`. If the query
   and the matched register row differ ONLY by identifier tokens
   (digits, cardinals, Roman numerals, single letters), reject the
   match — they're sibling entities (SPV #4 vs SPV #18, North vs
   South Branch), not the same company.

5. **Optional Splink rescoring** (gated by
   `enable_splink_sponsor_match`). For candidates in the ambiguous
   score band, load a pre-trained Splink model from
   `data/processed/sponsor_splink_model.json` and rescore the
   candidate set. Trained offline via `scripts/train_sponsor_splink.py`.
   Falls back to rule scores when the artifact is missing — the
   rule-based pipeline is the contract.

6. **Top-K results.** The single best match populates
   `SponsorStatus.matched_name`; up to `_TOP_K_ALTERNATIVES` runners-up
   surface as `SponsorStatus.alternative_matches` so the verdict agent
   can disambiguate when scores cluster.

Status mapping (LISTED / B_RATED / SUSPENDED / NOT_LISTED) is unchanged
from the legacy module; only the matching logic has been refactored.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterator, Optional

from ..config import settings
from ..data_freshness import age_days, is_stale
from ..schemas import SponsorAlternativeMatch, SponsorStatus

logger = logging.getLogger(__name__)


_STALE_WINDOW_DAYS = 14
_TOP_K_ALTERNATIVES = 2


# "X Ltd t/a Brand", "X t/as Brand", "X trading as Brand" — splits the
# legal entity from the trade name.
_TRADING_AS_RE = re.compile(r"\s+t/?a?s?\s+|\s+trading\s+as\s+", re.IGNORECASE)

# Legal-entity suffixes stripped to produce a "bare brand" alias. Order
# matters: multi-word forms first so "& Co Limited" matches before just
# "Limited". Captures UK plus the non-UK suffixes most common on the
# Home Office register (GmbH, AG, BV, A/S).
_LEGAL_SUFFIX_RE = re.compile(
    r"\s+(?:limited|ltd\.?|plc|llp|lp|llc|inc\.?|corp\.?|corporation"
    r"|gmbh|ag|s\.?a\.?|b\.?v\.?|a/s|n/v"
    r"|co\.?|company|group|holdings|services|partners|partnership)"
    r"(?:\s+|$)",
    re.IGNORECASE,
)

# Sponsor-register corporate dialect: generic-token abbreviations seen
# both on careers pages and in register entries. Curated; do not seed
# from training data — add entries only when a real false negative bites.
# Bidirectional: every entry generates two variants (full↔abbrev).
_ABBREVIATIONS: dict[str, str] = {
    "intl": "international",
    "natl": "national",
    "uk": "united kingdom",
    "gb": "great britain",
    "hldgs": "holdings",
    "svcs": "services",
    "mgmt": "management",
    "ent": "enterprises",
    "tech": "technology",
    "sys": "systems",
    "sol": "solutions",
    "comm": "communications",
    "fin": "financial",
    "mfg": "manufacturing",
    "assoc": "associates",
    "ins": "insurance",
    "med": "medical",
    "dev": "development",
}

# Known rebrands and trade-name aliases. Populate as product feedback
# flags misses; empty default is intentional (no rebrands are universal
# enough to bake in without evidence).
_REBRANDS: list[tuple[str, str]] = []

_CARDINAL_DIRECTIONS = frozenset(
    ["north", "south", "east", "west", "central", "upper", "lower"]
)
_ROMAN_NUMERALS = frozenset(
    ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
)


# ---------------------------------------------------------------------------
# Normalisation + alias expansion
# ---------------------------------------------------------------------------


def _normalise(name: str) -> str:
    """Lowercase, strip accents, drop punctuation, collapse whitespace.

    Does NOT strip legal suffixes — that's deliberate, since suffix
    presence is information for the discriminator veto and for some
    blocking decisions. Use `_strip_legal_suffix` on top when needed.
    """
    if not name:
        return ""
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower().strip()
    for ch in (",", ".", "(", ")", "[", "]", "'", '"', ":", ";"):
        name = name.replace(ch, " ")
    return " ".join(name.split())


def _strip_legal_suffix(name: str) -> str:
    """Iteratively strip trailing legal suffixes until stable."""
    prev = None
    while prev != name:
        prev = name
        name = _LEGAL_SUFFIX_RE.sub(" ", name).strip()
    return " ".join(name.split())


def _expand_query_aliases(name: str) -> list[str]:
    """Generate canonical surface forms for a query.

    Symmetric with the register-side index build (`_build_index`). Each
    returned alias is lowercased and de-duplicated. Three primary
    transforms:

    - legal-suffix strip (handles "Octopus Energy" vs "Octopus Energy Limited")
    - "t/a" split (handles "Capital on Tap" vs "New Wave Capital Ltd t/a Capital on Tap")
    - abbreviation swap (handles "ABC Intl" vs "ABC International")
    - "&" ↔ "and" swap (handles "B&Q" vs "B and Q")
    """
    base = _normalise(name)
    if not base:
        return []

    variants: set[str] = {base}

    bare = _strip_legal_suffix(base)
    if bare and bare != base:
        variants.add(bare)

    parts = _TRADING_AS_RE.split(base, maxsplit=1)
    if len(parts) > 1:
        ta = parts[1].strip()
        if ta:
            variants.add(ta)
            ta_bare = _strip_legal_suffix(ta)
            if ta_bare and ta_bare != ta:
                variants.add(ta_bare)

    if "&" in base:
        variants.add(base.replace("&", " and "))
    if " and " in base:
        variants.add(base.replace(" and ", " & "))

    for variant in list(variants):
        toks = set(variant.split())
        for abbrev, expansion in _ABBREVIATIONS.items():
            if abbrev in toks:
                variants.add(_collapse(variant.replace(abbrev, expansion)))
            if expansion in variant:
                variants.add(_collapse(variant.replace(expansion, abbrev)))

    for variant in list(variants):
        for old, new in _REBRANDS:
            if old in variant:
                variants.add(_collapse(variant.replace(old, new)))
            if new in variant:
                variants.add(_collapse(variant.replace(new, old)))

    return sorted({v for v in variants if v})


def _collapse(s: str) -> str:
    return " ".join(s.split())


# ---------------------------------------------------------------------------
# Discriminator-token veto
# ---------------------------------------------------------------------------


def _is_identifier_token(tok: str) -> bool:
    """Tokens that distinguish sibling entities."""
    if tok.isdigit():
        return True
    if tok in _CARDINAL_DIRECTIONS:
        return True
    if tok in _ROMAN_NUMERALS:
        return True
    if len(tok) == 1 and tok.isalpha():
        return True
    return False


def _discriminator_blocks_match(query: str, candidate: str) -> bool:
    """True when query and candidate differ ONLY by identifier tokens.

    Examples (blocks the match):
        "solar park 18"   vs "solar park 4"
        "north thames"    vs "south thames"
        "alpha holdings"  vs "alpha holdings b"

    Allows (does not block):
        "octopus energy"      vs "octopus energy limited"   (diff: "limited")
        "edf renewables"      vs "edf energy renewables"    (diff: "energy")
        "capital on tap"      vs "new wave capital on tap"  (diff: "new", "wave")
    """
    a = set(_strip_legal_suffix(_normalise(query)).split())
    b = set(_strip_legal_suffix(_normalise(candidate)).split())
    only_a, only_b = a - b, b - a
    if not only_a or not only_b:
        return False
    return (
        all(_is_identifier_token(t) for t in only_a)
        and all(_is_identifier_token(t) for t in only_b)
    )


# ---------------------------------------------------------------------------
# Multi-scorer ensemble
# ---------------------------------------------------------------------------


def _ensemble_score(query: str, candidate: str) -> tuple[float, dict[str, float]]:
    """Combine three rapidfuzz scorers into a single 0-100 score.

    Both sides are internally suffix-stripped before scoring so the
    function is robust to whatever surface form upstream alias
    expansion passes in. Without this, `token_sort_ratio` aggressively
    penalises length mismatch — "octopus energy" vs "octopus energy
    limited" drops to ~77 purely from suffix bloat, even though it's a
    legitimate match.

    Why three signals:
        WRatio:           rule-rich composite; rewards suffix/abbrev similarity
        token_sort_ratio: order-invariant token match; catches reordered names
        partial_ratio:    substring match; catches trade-name-in-legal-name

    Why min(WRatio, token_sort_ratio):
        A single weak signal vetoes. Cheap analogue of Splink's
        m-probability product — "Wise" vs "Aaron Wise Limited" stays
        high on WRatio (~92) and partial (~100) but token_sort drops
        sharply (1 of 3 tokens match), so min() catches the false
        positive a single-scorer pipeline accepts.
    """
    from rapidfuzz import fuzz

    q = _strip_legal_suffix(_normalise(query)) or _normalise(query)
    c = _strip_legal_suffix(_normalise(candidate)) or _normalise(candidate)
    s_w = float(fuzz.WRatio(q, c))
    s_t = float(fuzz.token_sort_ratio(q, c))
    s_p = float(fuzz.partial_ratio(q, c))
    combined = min(s_w, s_t)
    # Veto: large gap below combined signals "the substring inside one
    # name is too small to anchor the match" — apply a 10-point penalty
    # so the threshold catches it.
    if s_p < combined - 15:
        combined = max(combined - 10, s_p)
    return combined, {"wratio": s_w, "token_sort": s_t, "partial": s_p}


# ---------------------------------------------------------------------------
# Block-then-score index
# ---------------------------------------------------------------------------


@dataclass
class _SponsorIndex:
    df: object  # pandas DataFrame
    name_col: str
    rating_col: Optional[str]
    routes_col: Optional[str]
    last_updated_col: Optional[str]
    aliases: list[tuple[str, int]] = field(default_factory=list)
    first_token_block: dict[str, list[int]] = field(default_factory=dict)
    prefix4_block: dict[str, list[int]] = field(default_factory=dict)


_index: Optional[_SponsorIndex] = None
_index_lock = threading.Lock()


def _parquet_path() -> Path:
    return settings.data_dir / "processed" / "sponsor_register.parquet"


def _splink_model_path() -> Path:
    return settings.data_dir / "processed" / "sponsor_splink_model.json"


def _columns(df) -> dict[str, Optional[str]]:
    """Resolve our canonical column names against whichever variant
    the current Home Office CSV ships with — column names rotate
    publication-to-publication.
    """
    lowered = {c.lower(): c for c in df.columns}

    def pick(*candidates: str) -> Optional[str]:
        for cand in candidates:
            if cand in lowered:
                return lowered[cand]
        return None

    return {
        "name": pick("organisation name", "organisation_name", "name"),
        "rating": pick(
            "type & rating", "type and rating",
            "rating", "tier rating", "tier_rating",
        ),
        "routes": pick("route", "routes"),
        "last_updated": pick("last updated", "last_updated", "date"),
    }


def _build_index_from_df(df) -> _SponsorIndex:
    cols = _columns(df)
    name_col = cols["name"]
    if not name_col:
        raise ValueError("Sponsor parquet missing organisation-name column.")
    idx = _SponsorIndex(
        df=df,
        name_col=name_col,
        rating_col=cols["rating"],
        routes_col=cols["routes"],
        last_updated_col=cols["last_updated"],
    )

    seen: set[tuple[str, int]] = set()

    def add(alias_raw: str, row_idx: int) -> None:
        alias = _normalise(alias_raw)
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

    for row_idx, raw in enumerate(df[name_col].astype(str).tolist()):
        add(raw, row_idx)
        parts = _TRADING_AS_RE.split(raw, maxsplit=1)
        if len(parts) > 1:
            add(parts[1], row_idx)
        bare = _strip_legal_suffix(_normalise(raw))
        if bare:
            add(bare, row_idx)
            if len(parts) > 1:
                ta_bare = _strip_legal_suffix(_normalise(parts[1]))
                if ta_bare:
                    add(ta_bare, row_idx)
    return idx


def _build_index() -> _SponsorIndex:
    import pandas as pd

    path = _parquet_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Sponsor Register parquet not found at {path}. "
            "Run `python scripts/fetch_gov_data.py` first."
        )
    return _build_index_from_df(pd.read_parquet(path))


def _get_index() -> _SponsorIndex:
    global _index
    if _index is not None:
        return _index
    with _index_lock:
        if _index is None:
            _index = _build_index()
    return _index


def _reset_index_for_tests(idx: Optional[_SponsorIndex] = None) -> None:
    """Test-only hook. Inject a synthetic index or clear the cache."""
    global _index, _splink_linker
    _index = idx
    _splink_linker = None


def _candidate_alias_indices(query: str, idx: _SponsorIndex) -> list[int]:
    """Union of first-token and 4-char-prefix blocks.

    Fallback to a full scan when both blocks miss — short queries or
    typos at the start of the name shouldn't silently fail; the
    threshold will reject if they're not actually matches.
    """
    if not query:
        return []
    first_token = query.split(" ", 1)[0]
    candidates: set[int] = set()
    candidates.update(idx.first_token_block.get(first_token, []))
    candidates.update(idx.prefix4_block.get(query[:4], []))
    if not candidates:
        return list(range(len(idx.aliases)))
    return list(candidates)


# ---------------------------------------------------------------------------
# Splink rescoring (optional, off by default)
# ---------------------------------------------------------------------------


_splink_linker: Optional[object] = None
_splink_lock = threading.Lock()


@contextlib.contextmanager
def _quiet_splink_warnings() -> Iterator[None]:
    """Suppress `splink.internals.linker` WARNING logs for one predict() call.

    Splink emits "u values not fully trained" / "m values not fully trained"
    on every `predict()` invocation when any comparison level has an
    unestimated parameter — which happens by construction for the
    exact-name-match u-probability (random sampling finds zero exact
    matches in a 141k-row register, so EM has no data). The model still
    falls back to sensible defaults for those levels, so the warning is
    informational, not actionable. Scoped narrowly to the linker logger
    so real errors elsewhere stay visible.
    """
    linker_logger = logging.getLogger("splink.internals.linker")
    previous_level = linker_logger.level
    linker_logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        linker_logger.setLevel(previous_level)


def _load_splink_settings() -> Optional[dict]:
    """Return the trained Splink settings dict, or None if disabled/missing.

    Cached after the first successful load. Three failure modes — all
    return None and trigger fallback to rule-based scoring:
      - flag off
      - artifact missing
      - splink not installed
    """
    global _splink_linker
    if _splink_linker is not None:
        return _splink_linker  # type: ignore[return-value]
    if not getattr(settings, "enable_splink_sponsor_match", False):
        return None
    path = _splink_model_path()
    if not path.exists():
        logger.warning(
            "splink sponsor match enabled but model artifact missing at %s; "
            "falling back to rule-based scoring",
            path,
        )
        return None
    try:
        import splink  # noqa: F401
    except ImportError:
        logger.warning("splink not installed; rule-based scoring only")
        return None
    with _splink_lock:
        if _splink_linker is None:
            with open(path) as f:
                _splink_linker = json.load(f)
    return _splink_linker  # type: ignore[return-value]


def _splink_rescore(
    query: str, candidate_row_idxs: list[int], idx: _SponsorIndex
) -> dict[int, float]:
    """Rescore candidates with the trained Splink model.

    Returns `{row_idx: match_probability * 100}`. Empty dict on any
    failure — caller keeps the rule-based score.
    """
    if not candidate_row_idxs:
        return {}
    settings_dict = _load_splink_settings()
    if settings_dict is None:
        return {}
    try:
        import pandas as pd
        from splink import DuckDBAPI, Linker
    except ImportError:
        return {}
    try:
        # `link_only` 1-row left × N-row right setup. Splink's blocking
        # rules will fire as configured by the trainer; the candidate
        # set is already prefiltered so any additional blocking is a
        # belt-and-braces tightener.
        #
        # The settings dict is passed straight to `Linker(..., settings=...)`.
        # Splink 4 accepts `SettingsCreator | dict | Path | str` there.
        # Passing the dict from `save_model_to_json` is the documented
        # rehydration path; unpacking into `SettingsCreator(**dict)` fails
        # because `save_model_to_json` writes internal-only keys
        # (`sql_dialect`, `linker_uid`, ...) that the public constructor
        # doesn't accept.
        register_names = [
            _normalise(str(idx.df.iloc[row_idx][idx.name_col]))
            for row_idx in candidate_row_idxs
        ]
        candidates_df = pd.DataFrame(
            {
                "unique_id": [f"r_{i}" for i in candidate_row_idxs],
                "name": register_names,
                "first_token": [n.split(" ", 1)[0] for n in register_names],
            }
        )
        q_norm = _normalise(query)
        query_df = pd.DataFrame(
            {
                "unique_id": ["q_0"],
                "name": [q_norm],
                "first_token": [q_norm.split(" ", 1)[0]],
            }
        )
        db_api = DuckDBAPI()
        with _quiet_splink_warnings():
            linker = Linker(
                [query_df, candidates_df],
                settings_dict,
                db_api=db_api,
                input_table_aliases=["query", "register"],
                set_up_basic_logging=False,
            )
            predictions = linker.inference.predict(
                threshold_match_probability=0.0
            ).as_pandas_dataframe()
        out: dict[int, float] = {}
        for _, row in predictions.iterrows():
            left, right = row["unique_id_l"], row["unique_id_r"]
            other = left if right == "q_0" else right
            if not isinstance(other, str) or not other.startswith("r_"):
                continue
            row_idx = int(other.split("_", 1)[1])
            score = float(row["match_probability"]) * 100.0
            out[row_idx] = max(out.get(row_idx, 0.0), score)
        return out
    except Exception as exc:
        logger.warning(
            "splink rescoring failed: %s; falling back to rule-based scores", exc
        )
        return {}


# ---------------------------------------------------------------------------
# Top-K matcher
# ---------------------------------------------------------------------------


@dataclass
class _Match:
    row_idx: int
    alias: str
    score: float
    breakdown: dict[str, float]


def _rating_quality(rating: str) -> int:
    """Map a sponsor-rating string to a sort-preference score. Higher = better.

    A-rated (including provisional/expansion) sorts above NOT_LISTED
    (unknown), which sorts above B_RATED, which sorts above SUSPENDED.
    This is the principled fix for the entity-resolution gap #2:
    a suspended exact-name-match must never outrank an A-rated fuzzy-match.
    The user's question is "can this employer sponsor me?", not "is the
    name a perfect string match?".
    """
    r = (rating or "").lower()
    # A-rated — the gold standard. Skilled Worker + GBM + Expansion workers.
    if "(a" in r and "rating" in r:
        return 4
    # Provisional / Expansion Worker (provisional A-rating)
    if "provisional" in r or "expansion" in r:
        return 4
    # No listing at all — genuinely missing from the register
    if not r:
        return 2
    # B-rated — on the register but with restrictions
    if "(b" in r:
        return 1
    # Suspended — on the register but licence is inactive
    if "suspend" in r:
        return 0
    # Everything else (worker routes only, etc.) — unclear rating
    return 2


def _topk_matches(
    company_name: str, threshold: float, top_k: int
) -> list[_Match]:
    idx = _get_index()
    query_variants = _expand_query_aliases(company_name)
    if not query_variants:
        return []

    best_per_row: dict[int, _Match] = {}

    for q in query_variants:
        for alias_idx in _candidate_alias_indices(q, idx):
            alias, row_idx = idx.aliases[alias_idx]
            score, breakdown = _ensemble_score(q, alias)
            if score < threshold:
                continue
            existing = best_per_row.get(row_idx)
            if existing and existing.score >= score:
                continue
            best_per_row[row_idx] = _Match(
                row_idx=row_idx, alias=alias, score=score, breakdown=breakdown,
            )

    if not best_per_row:
        return []

    # Splink rescoring on the ambiguous band only. Cheap enough to
    # extend later to the full set if precision is the bottleneck.
    if getattr(settings, "enable_splink_sponsor_match", False):
        lo = float(getattr(settings, "sponsor_ambiguous_band_low", 80.0))
        hi = float(getattr(settings, "sponsor_ambiguous_band_high", 95.0))
        ambiguous = [m for m in best_per_row.values() if lo <= m.score <= hi]
        if ambiguous:
            splink_scores = _splink_rescore(
                company_name, [m.row_idx for m in ambiguous], idx,
            )
            for m in ambiguous:
                if m.row_idx in splink_scores:
                    m.breakdown["splink"] = splink_scores[m.row_idx]
                    m.score = splink_scores[m.row_idx]

    surviving: list[_Match] = []
    for m in sorted(
        best_per_row.values(),
        key=lambda x: (
            -_rating_quality(str(idx.df.iloc[x.row_idx][idx.rating_col]) if idx.rating_col else ""),
            -x.score,
        ),
    ):
        register_name = str(idx.df.iloc[m.row_idx][idx.name_col])
        if _discriminator_blocks_match(company_name, register_name):
            continue
        surviving.append(m)
        if len(surviving) >= top_k:
            break
    return surviving


# ---------------------------------------------------------------------------
# Status mapping (unchanged from the legacy module)
# ---------------------------------------------------------------------------


def _map_status(rating: str) -> str:
    r = (rating or "").lower()
    if "suspend" in r:
        return "SUSPENDED"
    m = re.search(r"\(\s*([ab])\b", r)
    if m:
        return "B_RATED" if m.group(1) == "b" else "LISTED"
    if "provisional" in r or "expansion" in r:
        return "LISTED"
    return "NOT_LISTED"


def _last_updated(df, col: Optional[str]) -> Optional[date]:
    if col is None:
        return None
    try:
        val = df[col].dropna().iloc[0]
        if isinstance(val, str):
            return datetime.strptime(val[:10], "%Y-%m-%d").date()
    except Exception:
        return None
    return None


def _freshness_status() -> str:
    if is_stale(_parquet_path(), window_days=_STALE_WINDOW_DAYS):
        logger.warning(
            "sponsor_register parquet is stale or has no freshness sidecar; "
            "verdict will mark source_status=STALE."
        )
        return "STALE"
    return "OK"


def _register_age_days() -> Optional[int]:
    """Freshness gradient (architecture gap #9). Surface the actual age
    so the verdict can distinguish 1-day-old from 13-day-old data."""
    return age_days(_parquet_path())


def _match_confidence(best_score: float, threshold: float) -> float:
    """Map a fuzzy-match score (0-100) to a 0.0-1.0 confidence.

    >95 → 1.0 (exact/CRN match), 92-95 → 0.9, 85-92 → 0.7,
    80-85 → 0.5, <80 → 0.3. These are calibrated against the Splink
    rescoring band and the ambiguous_band thresholds in config.
    """
    if best_score >= 95:
        return 1.0
    if best_score >= 92:
        return 0.9
    if best_score >= 85:
        return 0.7
    if best_score >= 80:
        return 0.5
    return 0.3


def _match_path(best_score: float, threshold: float) -> str:
    """Map a fuzzy-match score to a MatchPath enum value."""
    if best_score >= 95:
        return "EXACT_NAME"
    if best_score >= 80:
        return "FUZZY_NAME"
    return "NO_MATCH"


# ---------------------------------------------------------------------------
# Public lookup with a stable signature for current callers.
# ---------------------------------------------------------------------------


def _lookup_sync(company_name: str) -> SponsorStatus:
    threshold = float(getattr(settings, "sponsor_match_threshold", 92.0))
    freshness_status = _freshness_status()
    reg_age = _register_age_days()
    no_match_defaults = dict(
        source_status=freshness_status,
        register_age_days=reg_age,
        match_confidence=0.0,
        match_path="NO_MATCH",
    )
    try:
        idx = _get_index()
    except FileNotFoundError as e:
        logger.error("%s", e)
        return SponsorStatus(
            status="NOT_LISTED",
            matched_name=None,
            **no_match_defaults,
        )
    except Exception as e:  # pragma: no cover — guard against pandas/parquet errors
        logger.error("Sponsor index build failed: %s", e)
        return SponsorStatus(
            status="NOT_LISTED",
            matched_name=None,
            **no_match_defaults,
        )

    matches = _topk_matches(
        company_name, threshold=threshold, top_k=1 + _TOP_K_ALTERNATIVES,
    )
    if not matches:
        return SponsorStatus(
            status="NOT_LISTED",
            matched_name=None,
            **no_match_defaults,
        )

    best = matches[0]
    row = idx.df.iloc[best.row_idx]
    matched_name = str(row[idx.name_col])
    rating = str(row[idx.rating_col]) if idx.rating_col else ""
    routes_raw = str(row[idx.routes_col]) if idx.routes_col else ""
    visa_routes = [r.strip() for r in routes_raw.split(",") if r.strip()]

    # Dedup by organisation name — the register has rows with identical
    # Organisation Name (multiple filings of the same legal entity).
    # Surfacing the same string twice in alternatives is noise; we keep
    # only the highest-scoring instance per name.
    alternative_matches: list[SponsorAlternativeMatch] = []
    seen_alt_names: set[str] = {matched_name}
    for m in matches[1:]:
        alt_row = idx.df.iloc[m.row_idx]
        alt_name = str(alt_row[idx.name_col])
        if alt_name in seen_alt_names:
            continue
        seen_alt_names.add(alt_name)
        alt_rating = str(alt_row[idx.rating_col]) if idx.rating_col else ""
        alternative_matches.append(
            SponsorAlternativeMatch(
                matched_name=alt_name,
                rating=alt_rating or None,
                status=_map_status(alt_rating),
                score=round(m.score, 1),
            )
        )

    return SponsorStatus(
        status=_map_status(rating),
        matched_name=matched_name,
        rating=rating or None,
        visa_routes=visa_routes,
        last_register_update=_last_updated(idx.df, idx.last_updated_col),
        register_age_days=_register_age_days(),
        match_confidence=_match_confidence(best.score, threshold),
        match_path=_match_path(best.score, threshold),
        source_status=_freshness_status(),
        alternative_matches=alternative_matches,
    )


async def lookup(
    company_name: str,
    *,
    identity=None,
) -> SponsorStatus:
    """Match a company against the Sponsor Register.

    `identity` (optional `CompanyIdentity`) lets the unified resolver
    pass in a higher-quality canonical name + the full alias set
    (legal names, trading names, previous company names) from Companies
    House. When provided, we try EVERY name the resolver found and
    keep the best A-rated match across all of them — this is the
    principled fix for architecture gap #2.

    Without `identity`, falls back to the single raw `company_name`.
    """
    # Gather every name the resolver knows about. Running the fuzzy
    # match against all of them catches the case where the trading
    # name is unlicensed but a previous legal name IS on the register.
    names_to_try: list[str] = [company_name]
    if identity is not None:
        canonical = getattr(identity, "canonical_name", None)
        if canonical and canonical not in names_to_try and canonical != company_name:
            names_to_try.append(canonical)
        for attr in ("aliases", "trading_names", "previous_company_names"):
            extras = getattr(identity, attr, None) or []
            for n in extras:
                if isinstance(n, str) and n.strip() and n.strip() not in names_to_try:
                    names_to_try.append(n.strip())

    if len(names_to_try) == 1:
        return await asyncio.to_thread(_lookup_sync, company_name)

    # Run all names in parallel, pick the best A-rated match.
    # rating_quality encodes: A-rated=4 > unknown/NOT_LISTED=2 >
    # B_RATED=1 > SUSPENDED=0. Tie-break by matched_name presence.
    loop = asyncio.get_running_loop()
    results = await asyncio.gather(
        *(loop.run_in_executor(None, _lookup_sync, n) for n in names_to_try),
        return_exceptions=True,
    )

    best: Optional[SponsorStatus] = None
    best_q = -1
    for r in results:
        if isinstance(r, BaseException):
            continue
        if not isinstance(r, SponsorStatus):
            continue
        q = _rating_quality(r.rating or "")
        if r.matched_name and q > best_q:
            best = r
            best_q = q
        elif r.matched_name and q == best_q and best is None:
            best = r

    if best is not None:
        return best
    # All name searches failed — return the first non-exception result
    # (all should be NOT_LISTED), or the raw-company-name fallback.
    for r in results:
        if isinstance(r, SponsorStatus):
            return r
    return await asyncio.to_thread(_lookup_sync, company_name)
