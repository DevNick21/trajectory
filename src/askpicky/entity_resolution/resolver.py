"""resolve_company_identity — the unified resolver.

Pipeline (short-circuit on each anchor):

  1. Cache hit by CRN or by normalised alias.
  2. CRN hint (caller already knows the number e.g. from a previous run).
  3. Sponsor Register fuzzy match — uses the ensemble + Splink rescoring
     pipeline that already lives in sub_agents.sponsor_register.
  4. Companies House live name search (top 5) → ensemble-score each
     candidate against the input + the sponsor-matched name → pick best
     above threshold. Anchors a CRN.
  5. Fallback: thin identity with just the raw name + confidence 0.0.

The resolver does NOT make LLM calls. It's a pure name + structured-data
resolution layer — cheap, deterministic, easy to test.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from ..config import settings
from .normaliser import (
    ensemble_score,
    expand_aliases,
    normalise_name,
    slugify,
    strip_legal_suffix,
)
from .schemas import CompanyIdentity, ResolutionTrace
from .store import find_by_alias, find_by_crn, find_by_identity_id, is_stale, upsert_identity

logger = logging.getLogger(__name__)


# Score floor for accepting a Companies House search hit as the anchor.
# Set high because CH search is generous — it returns "Apple Computer
# UK Ltd" when you ask for "Apple", but the actual employer may be a
# completely different legal entity sharing one word.
_CH_ACCEPT_THRESHOLD = 88.0

# Number of CH search hits to consider per alias. CH /search/companies
# is paginated but the top items are usually all we need; opening more
# pages costs another round trip + would only help when the right
# company is buried far down the list.
_CH_SEARCH_LIMIT = 5

# Stop pulling more aliases after this many — protects against
# pathological alias-expansion blow-ups on weird inputs.
_MAX_ALIASES = 8


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _local_search(name: str) -> list[dict]:
    """Search the local CH bulk-data parquet. Empty list if no parquet."""
    try:
        from .local_ch_index import search_by_name
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("local_ch_index unavailable: %s", exc)
        return []
    hits = search_by_name(name)
    return [h.as_search_item() for h in hits]


async def _ch_search(name: str, *, items_per_page: int = _CH_SEARCH_LIMIT) -> list[dict]:
    """Local CH parquet first; rate-limited API as fallback.

    The parquet (built by `scripts/fetch_ch_bulk.py`) gives us 5M UK
    companies + their previous names with zero rate limit. The API only
    runs when the parquet is missing — typically a fresh install before
    the operator has fetched the monthly snapshot.
    """
    local = _local_search(name)
    if local:
        return local

    api_key = settings.companies_house_api_key
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(
            base_url="https://api.company-information.service.gov.uk",
            auth=(api_key, ""),
            timeout=10.0,
        ) as client:
            resp = await client.get(
                "/search/companies",
                params={"q": name, "items_per_page": items_per_page},
            )
            if resp.status_code != 200:
                return []
            return resp.json().get("items", [])
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Companies House search failed for %r: %s", name, exc)
        return []


async def _ch_profile(crn: str) -> Optional[dict]:
    """Companies House /company/{number}. None on missing key or error."""
    api_key = settings.companies_house_api_key
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(
            base_url="https://api.company-information.service.gov.uk",
            auth=(api_key, ""),
            timeout=10.0,
        ) as client:
            resp = await client.get(f"/company/{crn}")
            if resp.status_code != 200:
                return None
            return resp.json()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Companies House profile fetch failed for %s: %s", crn, exc)
        return None


# Companies that hit ALL of these are shells / brand-squat artefacts,
# NOT the real trading entity. The resolver must refuse to anchor to
# one of these even if its name is an exact match for the query.
# Triggered the 2026-05-22 loveholidays misfire — a dissolved CRN
# incorporated 2025-04-03 with no filings was picked over the real
# WE LOVE HOLIDAYS LIMITED (active since 2011).
def _is_shell_candidate(hit: dict) -> tuple[bool, str]:
    """Heuristic: True when this hit looks like a brand-squat shell.

    Returns (is_shell, reason) so the trace can record WHY we skipped.
    Cheap pure-data check — runs on every CH search hit pre-score.
    """
    status = (hit.get("company_status") or "").lower()
    if status not in {"dissolved", "liquidation", "receivership"}:
        return False, ""

    # CH search items don't always carry incorporation_date; the
    # /company/{number} profile does. Read both shapes — when the
    # field is missing, default to "looks fine".
    date_of_creation = (
        hit.get("date_of_creation")
        or hit.get("incorporation_date")
        or (hit.get("date_of_cessation") and None)
    )
    if not date_of_creation:
        # No incorporation date in the search item — let the profile
        # fetch decide. Don't reject blindly.
        return False, ""

    try:
        from datetime import date as _date, datetime as _dt
        incorporated = _dt.strptime(date_of_creation, "%Y-%m-%d").date()
        age_days = (_date.today() - incorporated).days
    except (ValueError, TypeError):
        return False, ""

    # Dissolved AND under a year old = brand-squat shell. The real
    # employer at any meaningful scale has trading history.
    if age_days < 365:
        return True, f"dissolved + only {age_days} days old"
    return False, ""


def _score_ch_hits(
    raw_name: str, hits: list[dict],
) -> list[tuple[float, dict]]:
    """Score each CH search hit against the input. Returns sorted (desc).

    Shell candidates (dissolved + freshly-incorporated brand squats)
    are dropped before scoring — these are the loveholidays-style
    misfires the resolver MUST refuse to anchor.
    """
    scored: list[tuple[float, dict]] = []
    for hit in hits:
        candidate = hit.get("title") or ""
        if not candidate:
            continue
        is_shell, reason = _is_shell_candidate(hit)
        if is_shell:
            logger.info(
                "Dropping shell candidate %s (%s): %s",
                hit.get("company_number"), candidate, reason,
            )
            continue
        combined, _ = ensemble_score(raw_name, candidate)
        scored.append((combined, hit))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def _domain_to_alias_seeds(domain: Optional[str]) -> list[str]:
    """Turn a domain like 'loveholidays.com' into extra alias seeds.

    Brand-name domains often differ from the legal name (drop "the",
    "we", "ltd"). Feeding the bare stem AND a small set of common
    prefix variants to the alias expander recovers matches like
    loveholidays -> WE LOVE HOLIDAYS LIMITED that pure first-token
    blocking can never reach.
    """
    if not domain:
        return []
    # Strip protocol + www + everything after the first slash.
    stem = domain.lower().strip()
    for prefix in ("https://", "http://", "www."):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
    stem = stem.split("/", 1)[0]
    # Drop the TLD chunk — keep loveholidays from loveholidays.com.
    label = stem.rsplit(".", 1)[0].split(".")[-1]
    if not label or len(label) < 3:
        return []
    seeds = {label}
    # Common prefixed variants. "we" / "the" / "your" prefixes show up
    # in legal names where the brand drops them.
    for prefix in ("we ", "the ", "your "):
        seeds.add(prefix + label)
    return sorted(seeds)


async def _sponsor_lookup_async(name: str):
    """Wrap the (sync) sponsor-register lookup in a thread."""
    from ..sub_agents.sponsor_register import _lookup_sync
    return await asyncio.to_thread(_lookup_sync, name)


async def resolve_company_identity(
    raw_name: str,
    *,
    domain: Optional[str] = None,
    crn_hint: Optional[str] = None,
    additional_aliases: Optional[list[str]] = None,
    use_cache: bool = True,
) -> CompanyIdentity:
    """Resolve an employer name to a canonical identity.

    Always returns a CompanyIdentity, even on total resolution failure
    — the worst case is a thin row with `confidence=0` and just the
    raw input as the canonical name. Downstream code can still cache
    against that.
    """
    trace = ResolutionTrace(raw_input=raw_name)
    sources: list[str] = []

    if not raw_name or not raw_name.strip():
        trace.chosen_via = "fallback_raw"
        return _thin_identity(raw_name or "Unknown", trace, sources)

    # 1. CRN hint short-circuit (cache hit + verify).
    if crn_hint:
        cached = await find_by_crn(crn_hint) if use_cache else None
        if cached and not is_stale(cached):
            trace.chosen_via = "cache_hit_crn"
            cached.trace = trace
            return cached
        profile = await _ch_profile(crn_hint)
        if profile:
            trace.chosen_via = "crn_hint"
            sources.append("crn_hint")
            identity = await _identity_from_ch_profile(
                profile, raw_name=raw_name, domain=domain,
                trace=trace, sources=sources,
            )
            await _enrich_with_sponsor(identity, raw_name=raw_name, trace=trace)
            await upsert_identity(identity)
            return identity

    # 2. Alias expansion + cache lookup by exact alias match.
    aliases = expand_aliases(raw_name)
    # Domain-derived seeds give us a second anchor when the brand is
    # buried inside a legal name (loveholidays -> we love holidays).
    for seed in _domain_to_alias_seeds(domain):
        for variant in expand_aliases(seed):
            if variant and variant not in aliases:
                aliases.append(variant)
    if additional_aliases:
        for extra in additional_aliases:
            normalised = normalise_name(extra)
            if normalised and normalised not in aliases:
                aliases.append(normalised)
    aliases = aliases[:_MAX_ALIASES]
    trace.aliases_tried = aliases

    if use_cache:
        for alias in aliases:
            cached = await find_by_alias(alias)
            if cached and not is_stale(cached):
                trace.chosen_via = "cache_hit_slug"
                cached.trace = trace
                return cached
        slug_identity_id = f"name:{slugify(raw_name)}"
        cached = await find_by_identity_id(slug_identity_id)
        if cached and not is_stale(cached):
            trace.chosen_via = "cache_hit_slug"
            cached.trace = trace
            return cached

    # 3. Sponsor Register pass first. Gives us a high-confidence
    #    matched_name when the company holds a licence; useful even
    #    when CH search is ambiguous.
    sponsor_status_obj = None
    try:
        sponsor_status_obj = await _sponsor_lookup_async(raw_name)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Sponsor lookup failed during resolve: %s", exc)
    if sponsor_status_obj and sponsor_status_obj.matched_name:
        sources.append("sponsor_register")

    # 4. Companies House search across aliases, score, pick best.
    pooled_hits: dict[str, dict] = {}
    for alias in aliases:
        hits = await _ch_search(alias)
        for hit in hits:
            crn = hit.get("company_number")
            if crn and crn not in pooled_hits:
                pooled_hits[crn] = hit
    # Add the sponsor-matched name to the search if we have it and it
    # differs — the matched_name is often closer to the official legal
    # form than the JD's casual rendering.
    if sponsor_status_obj and sponsor_status_obj.matched_name:
        extra_hits = await _ch_search(sponsor_status_obj.matched_name)
        for hit in extra_hits:
            crn = hit.get("company_number")
            if crn and crn not in pooled_hits:
                pooled_hits[crn] = hit
    trace.candidates_considered = len(pooled_hits)

    if pooled_hits:
        scored = _score_ch_hits(raw_name, list(pooled_hits.values()))
        # If we have a sponsor match, also score CH candidates against the
        # sponsor's canonical name. Best of the two scores wins.
        if sponsor_status_obj and sponsor_status_obj.matched_name:
            sponsor_scored = _score_ch_hits(
                sponsor_status_obj.matched_name, list(pooled_hits.values()),
            )
            score_by_crn: dict[str, tuple[float, dict]] = {}
            for score, hit in scored + sponsor_scored:
                crn = hit.get("company_number")
                if not crn:
                    continue
                existing = score_by_crn.get(crn)
                if existing is None or score > existing[0]:
                    score_by_crn[crn] = (score, hit)
            scored = sorted(
                score_by_crn.values(), key=lambda x: x[0], reverse=True,
            )

        if scored and scored[0][0] >= _CH_ACCEPT_THRESHOLD:
            top_score, top_hit = scored[0]
            crn = top_hit.get("company_number")

            # LAYER 6 — LLM-judge fallback on ambiguous picks.
            # The deterministic layers don't catch every long-tail edge
            # case (sites without a discoverable footer, ties between
            # active candidates, fresh-but-not-shell incorporations).
            # On those we route to a cheap Haiku judge that sees the
            # candidate set + the scraped page context and picks.
            # Otherwise we trust the deterministic top pick.
            second_score = scored[1][0] if len(scored) > 1 else None
            from .judge import (
                JudgeCandidate,
                judge_candidates,
                should_invoke_judge,
            )
            if should_invoke_judge(
                top_score=top_score,
                second_score=second_score,
                top_hit=top_hit,
            ):
                from datetime import date as _date, datetime as _dt
                judge_inputs: list[JudgeCandidate] = []
                for score, hit in scored[:5]:
                    doc = hit.get("date_of_creation") or hit.get("incorporation_date")
                    age_days = None
                    if doc:
                        try:
                            age_days = (
                                _date.today() - _dt.strptime(doc, "%Y-%m-%d").date()
                            ).days
                        except (ValueError, TypeError):
                            pass
                    judge_inputs.append(JudgeCandidate(
                        company_number=hit.get("company_number") or "",
                        company_name=hit.get("title") or "",
                        company_status=(hit.get("company_status") or None),
                        date_of_creation=doc,
                        ensemble_score=score,
                        incorporation_age_days=age_days,
                    ))
                judged_crn = await judge_candidates(
                    raw_name=raw_name,
                    domain=domain,
                    candidates=judge_inputs,
                )
                if judged_crn:
                    # Re-rank: the judge's pick wins. Pull its hit to
                    # top of `scored` so the rest of the flow uses it.
                    for i, (s, h) in enumerate(scored):
                        if h.get("company_number") == judged_crn:
                            top_score, top_hit = s, h
                            crn = judged_crn
                            sources.append("llm_judge")
                            break

            trace.chosen_via = "companies_house_search"
            trace.chosen_score = top_score
            if "companies_house" not in sources:
                sources.append("companies_house")
            profile = await _ch_profile(crn) if crn else None
            if profile:
                identity = await _identity_from_ch_profile(
                    profile, raw_name=raw_name, domain=domain,
                    trace=trace, sources=sources,
                )
            else:
                # Search hit without a profile — still useful as an anchor.
                identity = CompanyIdentity(
                    identity_id=f"crn:{crn}" if crn else f"name:{slugify(raw_name)}",
                    canonical_name=top_hit.get("title") or raw_name,
                    aliases=aliases,
                    crn=crn,
                    domain=domain,
                    confidence=top_score / 100.0,
                    sources=sources,
                    trace=trace,
                    resolved_at=_now(),
                )
            _merge_sponsor(identity, sponsor_status_obj, raw_name=raw_name)
            await upsert_identity(identity)
            return identity

    # 5. No CH anchor. If sponsor match exists, identity is name-anchored
    #    by the sponsor-side canonical. Else fully thin.
    if sponsor_status_obj and sponsor_status_obj.matched_name:
        trace.chosen_via = "sponsor_register_search"
        identity = CompanyIdentity(
            identity_id=f"name:{slugify(sponsor_status_obj.matched_name)}",
            canonical_name=sponsor_status_obj.matched_name,
            aliases=aliases,
            domain=domain,
            confidence=0.7,  # sponsor-anchored without CRN — high but not 1
            sources=sources,
            trace=trace,
            resolved_at=_now(),
        )
        _merge_sponsor(identity, sponsor_status_obj, raw_name=raw_name)
        await upsert_identity(identity)
        return identity

    trace.chosen_via = "fallback_raw"
    return _thin_identity(raw_name, trace, sources)


def _thin_identity(
    raw_name: str, trace: ResolutionTrace, sources: list[str],
) -> CompanyIdentity:
    aliases = expand_aliases(raw_name) if raw_name else []
    canonical = strip_legal_suffix(normalise_name(raw_name)) or raw_name
    return CompanyIdentity(
        identity_id=f"name:{slugify(raw_name)}",
        canonical_name=canonical or raw_name,
        aliases=aliases,
        confidence=0.0,
        sources=sources,
        trace=trace,
        resolved_at=_now(),
    )


async def _identity_from_ch_profile(
    profile: dict,
    *,
    raw_name: str,
    domain: Optional[str],
    trace: ResolutionTrace,
    sources: list[str],
) -> CompanyIdentity:
    crn = profile.get("company_number")
    canonical = profile.get("company_name") or raw_name
    legal_names = [canonical]
    # Previous names surface as trading_names for retroactive matching.
    trading_names: list[str] = []
    for prev in profile.get("previous_company_names") or []:
        name = prev.get("name") if isinstance(prev, dict) else None
        if name:
            trading_names.append(name)
    aliases = list({
        *expand_aliases(canonical),
        *expand_aliases(raw_name),
        *[normalise_name(n) for n in trading_names],
    })
    return CompanyIdentity(
        identity_id=f"crn:{crn}" if crn else f"name:{slugify(canonical)}",
        canonical_name=canonical,
        aliases=sorted([a for a in aliases if a]),
        legal_names=legal_names,
        trading_names=trading_names,
        crn=crn,
        company_status=str(profile.get("company_status") or "").upper() or None,
        domain=domain,
        confidence=1.0 if crn else 0.5,
        sources=sources,
        trace=trace,
        resolved_at=_now(),
    )


async def _enrich_with_sponsor(
    identity: CompanyIdentity, *, raw_name: str, trace: ResolutionTrace,
) -> None:
    """Attach sponsor-register status to an already-resolved identity."""
    try:
        result = await _sponsor_lookup_async(
            identity.canonical_name or raw_name,
        )
    except Exception:  # pragma: no cover - defensive
        return
    _merge_sponsor(identity, result, raw_name=raw_name)


def _merge_sponsor(identity: CompanyIdentity, sponsor_status_obj, *, raw_name: str) -> None:
    if not sponsor_status_obj:
        return
    matched = getattr(sponsor_status_obj, "matched_name", None)
    if matched:
        identity.sponsor_register_name = matched
        identity.sponsor_status = getattr(sponsor_status_obj, "status", None)
        if "sponsor_register" not in identity.sources:
            identity.sources.append("sponsor_register")
