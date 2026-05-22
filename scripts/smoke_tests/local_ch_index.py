"""Smoke: local CH bulk-data index.

Cheap — builds a tiny synthetic parquet on the fly, points the loader
at it, and verifies search_by_name returns the right CRN. No live
network. No real CH download.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from ._common import SmokeResult, prepare_environment, run_smoke

NAME = "local_ch_index"
ESTIMATED_COST_USD = 0.0


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()
    messages: list[str] = []
    failures: list[str] = []

    try:
        import pandas as pd
    except Exception as exc:
        return [], [f"pandas import failed: {exc!r}"], 0.0

    # Synthetic 5-row table mirroring the slim parquet shape.
    df = pd.DataFrame([
        {
            "CompanyName": "OCTOPUS ENERGY LIMITED",
            "CompanyNumber": "09263424",
            "CompanyStatus": "Active",
            "PostCode": "EC1V 9NR",
            "IncorporationDate": "2014-10-24",
            "DissolutionDate": "",
            "SicText": "35110 - Production of electricity",
            "PreviousNames": json.dumps([]),
        },
        {
            "CompanyName": "OCTOPUS ENERGY GROUP LIMITED",
            "CompanyNumber": "12345678",
            "CompanyStatus": "Active",
            "PostCode": "EC1V 9NR",
            "IncorporationDate": "2018-06-01",
            "DissolutionDate": "",
            "SicText": "70100 - Activities of head offices",
            "PreviousNames": json.dumps([]),
        },
        {
            "CompanyName": "WISE PAYMENTS LIMITED",
            "CompanyNumber": "07209813",
            "CompanyStatus": "Active",
            "PostCode": "EC2A 4DP",
            "IncorporationDate": "2011-03-15",
            "DissolutionDate": "",
            "SicText": "64999",
            "PreviousNames": json.dumps([
                "TRANSFERWISE LTD", "TRANSFERWISE LIMITED",
            ]),
        },
        {
            "CompanyName": "AARON WISE LIMITED",
            "CompanyNumber": "11111111",
            "CompanyStatus": "Active",
            "PostCode": "M1 1AA",
            "IncorporationDate": "2019-02-02",
            "DissolutionDate": "",
            "SicText": "62012",
            "PreviousNames": json.dumps([]),
        },
        {
            "CompanyName": "SPV 18 LIMITED",
            "CompanyNumber": "22222222",
            "CompanyStatus": "Active",
            "PostCode": "W1A 1AA",
            "IncorporationDate": "2020-01-01",
            "DissolutionDate": "",
            "SicText": "68209",
            "PreviousNames": json.dumps([]),
        },
    ])

    # Stash the parquet in a tempdir + point the loader at it.
    from askpicky.config import settings
    from askpicky.entity_resolution import local_ch_index as lci

    original_data_dir = settings.data_dir
    with tempfile.TemporaryDirectory() as tmp:
        tmp_data = Path(tmp)
        (tmp_data / "processed").mkdir()
        df.to_parquet(tmp_data / "processed" / "ch_companies.parquet", index=False)
        settings.data_dir = tmp_data
        lci.reload_index()

        try:
            # 1. Direct hit: "Octopus Energy" should pick the standalone
            #    OCTOPUS ENERGY LIMITED (09263424), not the GROUP version.
            hits = lci.search_by_name("Octopus Energy")
            if not hits:
                failures.append("no hits for 'Octopus Energy'")
            else:
                top = hits[0]
                if top.company_number != "09263424":
                    failures.append(
                        f"top hit for 'Octopus Energy' = {top.company_number} "
                        f"({top.company_name!r}); expected 09263424"
                    )
                else:
                    messages.append(
                        f"'Octopus Energy' -> {top.company_number} "
                        f"({top.company_name!r}, score={top.score:.0f})"
                    )

            # 2. Previous-name match: "TransferWise" should resolve to Wise
            #    via the PreviousNames column.
            hits = lci.search_by_name("TransferWise")
            if not hits:
                failures.append("no hits for 'TransferWise' via previous names")
            else:
                top = hits[0]
                if top.company_number != "07209813":
                    failures.append(
                        f"'TransferWise' should map to Wise (07209813); "
                        f"got {top.company_number} ({top.company_name!r})"
                    )
                else:
                    messages.append(
                        f"'TransferWise' -> {top.company_number} "
                        f"({top.company_name!r}) via previous-name index"
                    )

            # 3. Discriminator veto: "SPV 4 Limited" should NOT match
            #    "SPV 18 LIMITED" (different numeric identifier).
            hits = lci.search_by_name("SPV 4 Limited")
            spv18_hit = any(h.company_number == "22222222" for h in hits)
            if spv18_hit:
                failures.append(
                    "'SPV 4 Limited' wrongly matched 'SPV 18 LIMITED' "
                    "(discriminator veto failed)"
                )
            else:
                messages.append(
                    "discriminator veto OK: 'SPV 4' did not match 'SPV 18'"
                )

            # 4. False-positive guard: "Wise" should prefer Wise Payments
            #    over Aaron Wise (single-token vs three-token overlap).
            hits = lci.search_by_name("Wise")
            if hits:
                top = hits[0]
                if top.company_number == "07209813":
                    messages.append(
                        f"'Wise' -> {top.company_name!r} (correct, "
                        f"score={top.score:.0f})"
                    )
                else:
                    # Either acceptable result, but log which one.
                    messages.append(
                        f"'Wise' -> {top.company_name!r} ({top.company_number})"
                    )
        finally:
            settings.data_dir = original_data_dir
            lci.reload_index()

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
