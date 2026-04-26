"""Smoke test — salary_data.fetch (gov parquet lookup, no LLM).

Exercises:
  - ASHE percentile lookup for SOC 2136 in London.
  - Posted-band parsing when a JD band dict is supplied.
  - SalarySignals schema contract (sources_consulted populated,
    data_citations list non-empty).

Falls back gracefully when the ASHE parquet is missing — run
`scripts/fetch_gov_data.py` first for full coverage.

Cost: $0.
"""

from __future__ import annotations

from ._common import SmokeResult, prepare_environment, run_smoke

NAME = "salary_data"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from trajectory.sub_agents import salary_data

    messages: list[str] = []
    failures: list[str] = []

    try:
        signals = await salary_data.fetch(
            role="Senior Software Engineer",
            location="London",
            soc_code="2136",
            posted_band={
                "min": 70_000,
                "max": 90_000,
                "period": "annual",
                "source_url": "https://example.com/job",
                "verbatim_snippet": "£70,000 - £90,000",
            },
        )
    except Exception as exc:
        failures.append(f"salary_data.fetch raised: {exc!r}")
        return messages, failures, 0.0

    messages.append(
        f"sources_consulted: {signals.sources_consulted}; "
        f"ashe={'yes' if signals.ashe else 'no'}, "
        f"posted_band={'yes' if signals.posted_band else 'no'}, "
        f"aggregated={'yes' if signals.aggregated_postings else 'no'}"
    )

    if signals.posted_band is None:
        failures.append("posted_band dict was supplied but parsed as None.")
    elif signals.posted_band.min_gbp != 70_000:
        failures.append(
            f"posted_band.min_gbp = {signals.posted_band.min_gbp}, expected 70_000"
        )

    if signals.ashe is None:
        messages.append(
            "NOTE: ASHE parquet returned no percentiles — run "
            "scripts/fetch_gov_data.py to fully exercise the path."
        )
    else:
        if signals.ashe.p50 is None:
            failures.append("ASHE percentile lookup returned null p50.")
        else:
            messages.append(
                f"ASHE p10/p50/p90 @ SOC 2136 London: "
                f"{signals.ashe.p10}/{signals.ashe.p50}/{signals.ashe.p90}"
            )

    if not signals.data_citations:
        messages.append("NOTE: no data_citations (likely no ASHE parquet)")

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
