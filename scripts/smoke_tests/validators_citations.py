"""Smoke test — citations validator resolves against fixture bundle (no LLM).

Exercises:
  - Valid url_snippet, gov_data, career_entry citations resolve.
  - Invalid variants get flagged.
  - extract_all_citations walks nested Pydantic output.

Cost: $0.
"""

from __future__ import annotations

import uuid

from ._common import (
    SmokeResult,
    load_fixture_bundle,
    now_utc_naive,
    prepare_environment,
    run_smoke,
)

NAME = "validators_citations"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from pydantic import BaseModel
    from trajectory.schemas import CareerEntry, Citation
    from trajectory.validators.citations import (
        build_context,
        extract_all_citations,
        validate_citation,
        validate_output,
    )

    messages: list[str] = []
    failures: list[str] = []

    bundle = load_fixture_bundle()

    entry = CareerEntry(
        entry_id="entry-smoke-001",
        user_id="smoke_user",
        kind="cv_bullet",
        raw_text="Shipped a thing.",
        created_at=now_utc_naive(),
    )
    ctx = await build_context(
        research_bundle=bundle,
        user_id="smoke_user",
        career_entries=[entry],
    )

    # Known-good citations from the fixture.
    good_url = Citation(
        kind="url_snippet",
        url="https://acmetech.io/careers",
        verbatim_snippet="Our engineering team ships autonomously.",
    )
    good_gov = Citation(
        kind="gov_data",
        data_field="sponsor_register.status",
        data_value="LISTED",
    )
    good_entry = Citation(kind="career_entry", entry_id=entry.entry_id)

    for name, c in (("good_url", good_url), ("good_gov", good_gov),
                    ("good_entry", good_entry)):
        ok, reason = validate_citation(c, ctx)
        if not ok:
            failures.append(f"{name} rejected: {reason}")
    messages.append("3 known-good citations accepted")

    # Known-bad citations.
    bad_snippet = Citation(
        kind="url_snippet",
        url="https://acmetech.io/careers",
        verbatim_snippet="This exact phrase does not appear in the fixture.",
    )
    bad_gov = Citation(
        kind="gov_data",
        data_field="sponsor_register.status",
        data_value="SUSPENDED",  # fixture says LISTED
    )
    bad_entry = Citation(kind="career_entry", entry_id=str(uuid.uuid4()))

    for name, c in (("bad_snippet", bad_snippet), ("bad_gov", bad_gov),
                    ("bad_entry", bad_entry)):
        ok, _reason = validate_citation(c, ctx)
        if ok:
            failures.append(f"{name} was accepted, expected rejection")
    messages.append("3 known-bad citations rejected")

    # extract_all_citations walks nested BaseModels.
    class Nested(BaseModel):
        citation: Citation
        citations: list[Citation]

    root = Nested(citation=good_url, citations=[good_gov, good_entry])
    found = extract_all_citations(root)
    if len(found) != 3:
        failures.append(f"extract_all_citations found {len(found)}, expected 3")

    # validate_output surfaces failure count matching bad citations.
    class Bundle(BaseModel):
        citations: list[Citation]

    failures_out = validate_output(Bundle(citations=[good_url, bad_snippet, bad_entry]), ctx)
    if len(failures_out) != 2:
        failures.append(
            f"validate_output returned {len(failures_out)} failures; expected 2"
        )
    else:
        messages.append("validate_output surfaced 2 failures as expected")

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
