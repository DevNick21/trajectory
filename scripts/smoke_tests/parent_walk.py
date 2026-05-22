"""Smoke: parent/subsidiary CRN walk (architecture gap #2).

Two layers:

  1. companies_house._extract_corporate_parents — exercises the PSC
     filter logic against fixture payloads (individual PSCs skipped,
     ceased PSCs skipped, dedup by name, corporate-only kinds).

  2. orchestrator._walk_parent_sponsors — mocks sponsor_register.lookup
     to verify: NOT_LISTED with no CH parents is a no-op; NOT_LISTED
     with corporate PSCs runs the re-lookup; matched parents land as
     alternative_matches with match_path=LOOKS_LIKE_SUB_ENTITY and
     status flipped to AMBIGUOUS.

No live network, no LLM. Cost: $0.
"""

from __future__ import annotations

import asyncio

from ._common import SmokeResult, prepare_environment, run_smoke

NAME = "parent_walk"
ESTIMATED_COST_USD = 0.0


_PSC_FIXTURE = [
    {
        "name": "Jane Smith",
        "kind": "individual-person-with-significant-control",
    },
    {
        "name": "ACME HOLDINGS PLC",
        "kind": "corporate-entity-person-with-significant-control",
        "identification": {"registration_number": "01234567"},
    },
    {
        "name": "ACME OFFSHORE LLC",
        "kind": "legal-person-person-with-significant-control",
        "identification": {"registration_number": None},
    },
    {
        "name": "Defunct Parent Ltd",
        "kind": "corporate-entity-person-with-significant-control",
        "identification": {"registration_number": "00112233"},
        "ceased_on": "2024-03-15",  # No longer in control; must skip.
    },
    {
        # Duplicate of ACME HOLDINGS PLC — must dedupe.
        "name": "Acme Holdings PLC",
        "kind": "corporate-entity-person-with-significant-control",
        "identification": {"registration_number": "01234567"},
    },
]


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()
    messages: list[str] = []
    failures: list[str] = []

    # ── Layer 1: PSC extractor ────────────────────────────────────────

    from askpicky.sub_agents.companies_house import _extract_corporate_parents

    parents = _extract_corporate_parents(_PSC_FIXTURE)

    if len(parents) != 2:
        failures.append(
            f"expected 2 corporate parents (PLC + LLC), got {len(parents)}: "
            f"{[p['name'] for p in parents]}"
        )
    else:
        messages.append(
            f"PSC extractor: {len(parents)} corporate parents "
            f"({[p['name'] for p in parents]})"
        )

    names_lower = {p["name"].lower() for p in parents}
    if "jane smith" in names_lower:
        failures.append("individual PSC leaked into corporate parents")
    if "defunct parent ltd" in names_lower:
        failures.append("ceased PSC leaked into corporate parents")
    # Dedup: the duplicate "Acme Holdings PLC" with the same CRN must
    # appear exactly once.
    name_counts: dict[str, int] = {}
    for p in parents:
        key = p["name"].lower()
        name_counts[key] = name_counts.get(key, 0) + 1
    if any(c > 1 for c in name_counts.values()):
        failures.append(
            f"corporate parents not deduped by name: {name_counts}"
        )
    else:
        messages.append("PSC extractor: dedupe + ceased + individual filters OK")

    # ── Layer 2: orchestrator._walk_parent_sponsors ───────────────────

    from askpicky.orchestrator import _walk_parent_sponsors
    from askpicky.schemas import (
        CompaniesHouseSnapshot,
        ParentCompany,
        SponsorAlternativeMatch,
        SponsorStatus,
    )

    # Fake sponsor_register agent — controllable lookup table.
    class _FakeSrAgent:
        def __init__(self, table: dict[str, SponsorStatus]) -> None:
            self.table = table
            self.calls: list[str] = []

        async def lookup(self, name: str) -> SponsorStatus:
            self.calls.append(name)
            return self.table.get(
                name,
                SponsorStatus(
                    status="NOT_LISTED",
                    matched_name=None,
                    match_confidence=0.0,
                    match_path="NO_MATCH",
                ),
            )

    # CH snapshot with two corporate parents.
    ch_with_parents = CompaniesHouseSnapshot(
        company_number="11112222",
        status="ACTIVE",
        company_name_official="Acme Subsidiary Ltd",
        sic_codes=["62012"],
        accounts_overdue=False,
        confirmation_statement_overdue=False,
        no_filings_in_years=0,
        resolution_to_wind_up=False,
        director_disqualifications=0,
        parent_companies=[
            ParentCompany(
                name="ACME HOLDINGS PLC",
                crn="01234567",
                kind="corporate-entity-person-with-significant-control",
            ),
            ParentCompany(
                name="UNLISTED PARENT LTD",
                crn="99887766",
                kind="corporate-entity-person-with-significant-control",
            ),
        ],
    )

    # CH snapshot with no parents (the SME case — no-op expected).
    ch_no_parents = ch_with_parents.model_copy(update={"parent_companies": []})

    # 1. NOT_LISTED + no parents → no-op
    sponsor_not_listed = SponsorStatus(
        status="NOT_LISTED",
        matched_name=None,
        match_confidence=0.0,
        match_path="NO_MATCH",
    )
    fake_sr = _FakeSrAgent({})
    out = await _walk_parent_sponsors(
        sponsor_status=sponsor_not_listed,
        ch_snapshot=ch_no_parents,
        sr_agent=fake_sr,
    )
    if out.status != "NOT_LISTED" or fake_sr.calls:
        failures.append(
            f"no-parents path should be a no-op; got status={out.status}, "
            f"calls={fake_sr.calls}"
        )
    else:
        messages.append("no-parents no-op: status stays NOT_LISTED")

    # 2. Already LISTED → no parent walk
    sponsor_listed = SponsorStatus(
        status="LISTED",
        matched_name="Acme Subsidiary Ltd",
        match_confidence=1.0,
        match_path="EXACT_NAME",
    )
    fake_sr = _FakeSrAgent({})
    out = await _walk_parent_sponsors(
        sponsor_status=sponsor_listed,
        ch_snapshot=ch_with_parents,
        sr_agent=fake_sr,
    )
    if out.status != "LISTED" or fake_sr.calls:
        failures.append(
            "LISTED path triggered parent walk; should skip"
        )
    else:
        messages.append("LISTED short-circuit: no parent walk attempted")

    # 3. NOT_LISTED + corporate parents, parent IS listed → AMBIGUOUS + alt match
    fake_sr = _FakeSrAgent({
        "ACME HOLDINGS PLC": SponsorStatus(
            status="LISTED",
            matched_name="Acme Holdings Plc",
            rating="A",
            match_confidence=1.0,
            match_path="EXACT_NAME",
        ),
        "UNLISTED PARENT LTD": SponsorStatus(
            status="NOT_LISTED",
            matched_name=None,
            match_confidence=0.0,
            match_path="NO_MATCH",
        ),
    })
    out = await _walk_parent_sponsors(
        sponsor_status=sponsor_not_listed,
        ch_snapshot=ch_with_parents,
        sr_agent=fake_sr,
    )
    if out.status != "AMBIGUOUS":
        failures.append(
            f"matched-parent should flip status to AMBIGUOUS; got {out.status}"
        )
    elif out.match_path != "LOOKS_LIKE_SUB_ENTITY":
        failures.append(
            f"matched-parent should set match_path=LOOKS_LIKE_SUB_ENTITY; "
            f"got {out.match_path}"
        )
    elif not any(
        m.matched_name == "Acme Holdings Plc"
        for m in out.alternative_matches
    ):
        failures.append(
            f"matched parent did not surface as alternative_match: "
            f"{[m.matched_name for m in out.alternative_matches]}"
        )
    else:
        messages.append(
            f"parent walk hit: status={out.status} "
            f"match_path={out.match_path} "
            f"alt_matches={[m.matched_name for m in out.alternative_matches]}"
        )
    if fake_sr.calls != ["ACME HOLDINGS PLC", "UNLISTED PARENT LTD"]:
        failures.append(
            f"unexpected parent-walk call list: {fake_sr.calls}"
        )

    # 4. NOT_LISTED + corporate parents, no parents listed → no-op (still NOT_LISTED)
    fake_sr = _FakeSrAgent({})  # All parents miss
    out = await _walk_parent_sponsors(
        sponsor_status=sponsor_not_listed,
        ch_snapshot=ch_with_parents,
        sr_agent=fake_sr,
    )
    if out.status != "NOT_LISTED":
        failures.append(
            f"no parents listed → status should stay NOT_LISTED; got {out.status}"
        )
    else:
        messages.append(
            "no parents listed: status stays NOT_LISTED (no spurious AMBIGUOUS)"
        )

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
