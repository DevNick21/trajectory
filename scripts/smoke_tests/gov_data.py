"""Smoke test — government data lookups (no LLM).

Exercises:
  - sponsor_register.lookup against a known A-rated company (`Monzo`)
  - soc_check.verify against a known eligible SOC code (2136)
  - companies_house.lookup if COMPANIES_HOUSE_API_KEY is set

These are the "moat" data sources behind the verdict. If any of them
can't resolve a real company, the demo loses its teeth — worth
checking explicitly before the recording.

Cost: $0. All parquet lookups + one gov API call.
"""

from __future__ import annotations

from ._common import (
    SmokeResult,
    build_test_user,
    get_logger,
    prepare_environment,
    require_env,
    run_smoke,
)

NAME = "gov_data"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from trajectory.sub_agents import companies_house, soc_check, sponsor_register
    from trajectory.schemas import ExtractedJobDescription

    log = get_logger(NAME)
    messages: list[str] = []
    failures: list[str] = []

    # ---- Sponsor Register --------------------------------------------------
    try:
        sponsor = await sponsor_register.lookup("Monzo Bank")
        messages.append(
            f"sponsor_register: Monzo -> status={sponsor.status}, "
            f"matched_name={sponsor.matched_name!r}"
        )
        if sponsor.status == "NOT_LISTED":
            failures.append(
                "Sponsor Register returned NOT_LISTED for Monzo — either the "
                "parquet is empty (run scripts/fetch_gov_data.py) or the "
                "register column names changed."
            )
    except Exception as exc:
        failures.append(f"sponsor_register.lookup raised: {exc!r}")

    try:
        missing = await sponsor_register.lookup("ThisCompanyDefinitelyDoesNotExist LLP")
        messages.append(f"sponsor_register (unknown): status={missing.status}")
        if missing.status != "NOT_LISTED":
            failures.append(
                f"Unknown company should return NOT_LISTED; got {missing.status!r}"
            )
    except Exception as exc:
        failures.append(f"sponsor_register.lookup (unknown) raised: {exc!r}")

    # ---- SOC Check ---------------------------------------------------------
    try:
        user = build_test_user("visa_holder")
        jd = ExtractedJobDescription(
            role_title="Senior Software Engineer",
            seniority_signal="senior",
            soc_code_guess="2136",
            soc_code_reasoning="JD mentions software engineering responsibilities",
            salary_band={"min": 65_000, "max": 85_000},
            location="London",
            remote_policy="hybrid",
            required_years_experience=5,
            required_skills=["python", "typescript"],
            posting_platform="company_site",
            hiring_manager_named=False,
            jd_text_full="dummy",
            specificity_signals=[],
            vagueness_signals=[],
        )
        soc = await soc_check.verify(jd=jd, user=user)
        messages.append(
            f"soc_check: 2136 -> going_rate={soc.going_rate_gbp}, "
            f"on_appendix={soc.on_appendix_skilled_occupations}, "
            f"below_threshold={soc.below_threshold}"
        )
        if soc.going_rate_gbp is None:
            failures.append(
                "SOC 2136 returned no going_rate — going_rates.parquet may be empty."
            )
    except Exception as exc:
        failures.append(f"soc_check.verify raised: {exc!r}")

    # ---- Companies House (only if the API key is set) ----------------------
    ch_missing = require_env("COMPANIES_HOUSE_API_KEY")
    if ch_missing:
        messages.append(f"companies_house: skipped — {ch_missing}")
    else:
        try:
            snap = await companies_house.lookup(company_name="Monzo Bank Limited")
            if snap is None:
                failures.append(
                    "companies_house.lookup returned None for 'Monzo Bank Limited'."
                )
            else:
                messages.append(
                    f"companies_house: Monzo Bank Limited -> status={snap.status}, "
                    f"company_number={snap.company_number!r}"
                )
        except Exception as exc:
            failures.append(f"companies_house.lookup raised: {exc!r}")

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
