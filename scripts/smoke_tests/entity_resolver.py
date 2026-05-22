"""Smoke: unified company identity resolver.

Cheap — no live network. Stubs the CH HTTP path so the resolver still
exercises its full state machine (cache miss → alias expand → CH
search → ensemble score → identity build) but doesn't depend on the
Companies House API being reachable.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from ._common import SmokeResult, prepare_environment, run_smoke

NAME = "entity_resolver"
ESTIMATED_COST_USD = 0.0


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()
    messages: list[str] = []
    failures: list[str] = []

    from askpicky.entity_resolution import (
        CompanyIdentity,
        resolve_company_identity,
    )
    from askpicky.entity_resolution import resolver as resolver_mod
    from askpicky.entity_resolution.normaliser import (
        ensemble_score,
        expand_aliases,
        slugify,
    )

    # 1. Alias expansion: "Acme & Co Ltd" should produce both "acme & co"
    #    and "acme and co" variants alongside the bare brand.
    aliases = expand_aliases("Acme & Co Ltd")
    if not any("and" in a for a in aliases):
        failures.append("expand_aliases didn't generate '&'→'and' variant")
    if not any(a == "acme" or a.startswith("acme") for a in aliases):
        failures.append("expand_aliases missing bare-brand variant")
    messages.append(f"alias expansion OK: {len(aliases)} variants for 'Acme & Co Ltd'")

    # 2. Slug stability: same input → same slug.
    if slugify("Acme Ltd") != slugify("Acme Limited"):
        failures.append("slugify not suffix-stable")
    messages.append("slugify is suffix-stable")

    # 3. Ensemble score: identical names should score 100; very different
    #    should score low.
    same_score, _ = ensemble_score("Octopus Energy", "Octopus Energy")
    diff_score, _ = ensemble_score("Octopus Energy", "Trafalgar Bakeries")
    if same_score < 99:
        failures.append(f"ensemble_score on identical inputs = {same_score} (expected ~100)")
    if diff_score > 50:
        failures.append(f"ensemble_score on dissimilar inputs = {diff_score} (expected <50)")
    messages.append(f"ensemble scores: same={same_score:.0f} different={diff_score:.0f}")

    # 4. End-to-end: stub the CH HTTP layer so we don't depend on live
    #    network. The resolver should:
    #      - try aliases
    #      - score the stubbed hits
    #      - pick the top hit above threshold
    #      - anchor a CRN
    captured_queries: list[str] = []

    async def _fake_ch_search(name: str, *, items_per_page: int = 5) -> list[dict]:
        captured_queries.append(name)
        return [
            {"title": "OCTOPUS ENERGY LIMITED", "company_number": "09263424"},
            {"title": "OCTOPUS ENERGY GROUP LIMITED", "company_number": "12345678"},
            {"title": "OCTOPUS LABS LIMITED", "company_number": "08888888"},
        ]

    async def _fake_ch_profile(crn: str) -> Optional[dict]:
        return {
            "company_number": crn,
            "company_name": "OCTOPUS ENERGY LIMITED",
            "company_status": "active",
            "previous_company_names": [],
        }

    async def _fake_sponsor(name: str):
        # The resolver tolerates None / no matched_name. Returning None
        # here means "no sponsor info", so the resolver falls through to
        # CH-anchored identity.
        return None

    original_search = resolver_mod._ch_search
    original_profile = resolver_mod._ch_profile
    original_sponsor = resolver_mod._sponsor_lookup_async
    resolver_mod._ch_search = _fake_ch_search
    resolver_mod._ch_profile = _fake_ch_profile
    resolver_mod._sponsor_lookup_async = _fake_sponsor

    try:
        identity = await resolve_company_identity("Octopus Energy", use_cache=False)
        if not isinstance(identity, CompanyIdentity):
            failures.append("resolver did not return CompanyIdentity")
            return messages, failures, ESTIMATED_COST_USD
        if identity.crn != "09263424":
            failures.append(
                f"expected CRN 09263424 from ensemble pick, got {identity.crn!r}"
            )
        if identity.identity_id != "crn:09263424":
            failures.append(
                f"identity_id should be 'crn:09263424', got {identity.identity_id!r}"
            )
        if identity.confidence < 0.9:
            failures.append(
                f"CRN-anchored identity should have confidence ~1.0, got {identity.confidence}"
            )
        if "companies_house" not in identity.sources:
            failures.append("identity.sources missing 'companies_house'")
        messages.append(
            f"resolver picked id={identity.identity_id} "
            f"canonical={identity.canonical_name!r} "
            f"conf={identity.confidence:.2f} "
            f"via={identity.trace.chosen_via}"
        )
        if not captured_queries:
            failures.append("resolver never queried CH (search stub uncalled)")
        else:
            messages.append(f"queried CH for {len(captured_queries)} alias(es)")

        # 5. Cache hit: a second resolve with use_cache=True should hit
        #    the SQLite cache. Verify by clearing the stub counter.
        captured_queries.clear()
        identity2 = await resolve_company_identity("Octopus Energy")
        if identity2.identity_id != identity.identity_id:
            failures.append(
                "cached re-resolve returned different identity_id "
                f"({identity2.identity_id!r} != {identity.identity_id!r})"
            )
        if captured_queries:
            # Cache hit means we should not have hit the search stub
            # again. (Strict: zero queries on the second pass.)
            failures.append(
                f"expected cache hit but resolver issued {len(captured_queries)} fresh CH searches"
            )
        else:
            messages.append("second resolve hit cache (zero CH queries)")
    finally:
        resolver_mod._ch_search = original_search
        resolver_mod._ch_profile = original_profile
        resolver_mod._sponsor_lookup_async = original_sponsor

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
