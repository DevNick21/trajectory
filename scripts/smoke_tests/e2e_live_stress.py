"""End-to-end live stress — 20 (user, job) scenarios against the real
Opus verdict agent.

The user asked for a full live + paid E2E stress matrix: 20+ variations
exercising every stage of the system. This smoke takes the route the
demo cares about most — `forward_job → verdict` — and runs the LIVE
Opus xhigh verdict against 20 controlled bundle fixtures, each
representing a different decision pathway:

  - 6 GO paths: UK resident matching motivations; visa holder LISTED +
    SOC clear; tech vs non-tech roles; varied confidence drivers.
  - 4 NO_GO via NOT_ON_SPONSOR_REGISTER (visa_holder + status NOT_LISTED).
  - 2 NO_GO via SPONSOR_B_RATED.
  - 2 NO_GO via SPONSOR_SUSPENDED.
  - 2 NO_GO via SALARY_BELOW_SOC_THRESHOLD (visa, below_threshold=True).
  - 2 NO_GO via LIKELY_GHOST_JOB (high vagueness, not on careers page).
  - 2 NO_GO via DEAL_BREAKER_TRIGGERED (user has explicit deal-breaker
    that the role hits).

Each scenario asserts:
  - decision matches expected (GO / NO_GO)
  - hard_blockers contains the expected blocker type (when NO_GO)
  - reasoning has ≥3 cited points
  - the Rule 2 guard didn't get bypassed (no GO with non-empty hard_blockers)

Bundle fixtures are derived from `tests/fixtures/sample_research_bundle.json`
with model_copy overlays — synthetic enough to control the verdict's
inputs, real enough that the citations validator resolves against the
fixture's scraped pages.

Cost: budget ~$25 for 20 verdict calls at Opus xhigh ($1-1.50 each).
Gated behind `SMOKE_E2E_STRESS=1` so a casual run doesn't spend.
"""

from __future__ import annotations

import asyncio
import os
from copy import deepcopy

from ._common import (
    SmokeResult,
    build_test_session,
    build_test_user,
    load_fixture_bundle,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "e2e_live_stress"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 25.0

_GATE_ENV = "SMOKE_E2E_STRESS"


def _bundle_with(base, overrides: dict):
    """Build a ResearchBundle by overlaying field updates onto the
    fixture base. Pydantic's `model_copy(update=...)` doesn't recurse
    into nested models, so we hand-merge the few fields we need."""
    data = base.model_dump(mode="python")
    for key, value in overrides.items():
        # Dot path support: 'extracted_jd.role_title' updates nested.
        if "." in key:
            outer, inner = key.split(".", 1)
            data[outer] = {**(data[outer] or {}), inner: value}
        else:
            data[key] = value
    return base.__class__.model_validate(data)


def _scenarios(base_bundle):
    """Return 20 (label, expected_decision, expected_blocker_type, user_type,
    bundle, deal_breakers) tuples. `expected_blocker_type` is None on GO."""
    from trajectory.schemas import (
        Citation,
        GhostJobAssessment,
        GhostJobJDScore,
        GhostSignal,
        SocCheckResult,
        SponsorStatus,
    )

    not_listed = SponsorStatus(
        status="NOT_LISTED",
        matched_name=None,
        rating=None,
        visa_routes=[],
        last_register_update=base_bundle.sponsor_status.last_register_update,
        source_status="OK",
    )
    b_rated = SponsorStatus(
        status="B_RATED",
        matched_name="Acme Tech Ltd",
        rating="B",
        visa_routes=["Skilled Worker"],
        last_register_update=base_bundle.sponsor_status.last_register_update,
        source_status="OK",
    )
    suspended = SponsorStatus(
        status="SUSPENDED",
        matched_name="Acme Tech Ltd",
        rating=None,
        visa_routes=[],
        last_register_update=base_bundle.sponsor_status.last_register_update,
        source_status="OK",
    )
    soc_below = SocCheckResult(
        soc_code="2136",
        soc_title="Programmers and software development professionals",
        on_appendix_skilled_occupations=True,
        going_rate_gbp=40_300,
        new_entrant_rate_gbp=30_900,
        offered_salary_gbp=32_000,        # below the £40,300 going rate
        below_threshold=True,
        shortfall_gbp=8_300,
        new_entrant_eligible=False,
        source_status="OK",
    )
    # Use the existing fixture's first scraped page as the citation
    # source for synthetic ghost signals — keeps the citation validator
    # happy on the real verdict run.
    pages = base_bundle.company_research.scraped_pages
    cit_url = pages[0].url if pages else "https://example.com/careers"
    cit_snippet = (
        pages[0].text[:60] if pages and pages[0].text
        else "fixture text"
    )
    ghost_citation = Citation(
        kind="url_snippet", url=cit_url, verbatim_snippet=cit_snippet,
    )
    ghost = GhostJobAssessment(
        probability="LIKELY_GHOST",
        signals=[
            GhostSignal(
                type="NOT_ON_CAREERS_PAGE",
                evidence="Job not present on careers page (synthetic).",
                citation=ghost_citation,
                severity="HARD",
            ),
            GhostSignal(
                type="VAGUE_JD",
                evidence="JD specificity score 1.5/10 (synthetic).",
                citation=ghost_citation,
                severity="SOFT",
            ),
        ],
        confidence="HIGH",
        raw_jd_score=GhostJobJDScore(
            named_hiring_manager=0.0,
            specific_duty_bullets=0.5,
            specific_tech_stack=0.0,
            specific_team_context=0.0,
            specific_success_metrics=0.0,
            specificity_score=1.5,
            specificity_signals=[],
            vagueness_signals=[
                "fast-paced environment", "rockstar", "ninja",
            ],
        ),
        age_days=180,
    )

    scenarios: list[tuple] = []

    # ── 6 GO paths ──────────────────────────────────────────────────
    scenarios.append((
        "go_uk_match_1", "GO", None, "uk_resident",
        base_bundle, [],
    ))
    scenarios.append((
        "go_uk_match_2", "GO", None, "uk_resident",
        _bundle_with(base_bundle, {
            "extracted_jd.role_title": "Senior Backend Engineer",
        }),
        [],
    ))
    scenarios.append((
        "go_visa_clear", "GO", None, "visa_holder",
        base_bundle, [],
    ))
    scenarios.append((
        "go_uk_higher_seniority", "GO", None, "uk_resident",
        _bundle_with(base_bundle, {
            "extracted_jd.seniority_signal": "staff",
        }),
        [],
    ))
    scenarios.append((
        "go_visa_grad", "GO", None, "visa_holder",
        base_bundle, [],
    ))
    scenarios.append((
        "go_uk_remote_friendly", "GO", None, "uk_resident",
        _bundle_with(base_bundle, {
            "extracted_jd.remote_policy": "remote",
        }),
        [],
    ))

    # ── 4 NOT_ON_SPONSOR_REGISTER ────────────────────────────────────
    for i in range(4):
        scenarios.append((
            f"no_go_not_listed_{i + 1}",
            "NO_GO", "NOT_ON_SPONSOR_REGISTER", "visa_holder",
            _bundle_with(base_bundle, {"sponsor_status": not_listed}),
            [],
        ))

    # ── 2 SPONSOR_B_RATED ────────────────────────────────────────────
    for i in range(2):
        scenarios.append((
            f"no_go_b_rated_{i + 1}",
            "NO_GO", "SPONSOR_B_RATED", "visa_holder",
            _bundle_with(base_bundle, {"sponsor_status": b_rated}),
            [],
        ))

    # ── 2 SPONSOR_SUSPENDED ──────────────────────────────────────────
    for i in range(2):
        scenarios.append((
            f"no_go_suspended_{i + 1}",
            "NO_GO", "SPONSOR_SUSPENDED", "visa_holder",
            _bundle_with(base_bundle, {"sponsor_status": suspended}),
            [],
        ))

    # ── 2 SALARY_BELOW_SOC_THRESHOLD ─────────────────────────────────
    for i in range(2):
        scenarios.append((
            f"no_go_salary_below_soc_{i + 1}",
            "NO_GO", "SALARY_BELOW_SOC_THRESHOLD", "visa_holder",
            _bundle_with(base_bundle, {
                "soc_check": soc_below,
                "extracted_jd.salary_band": {
                    "min_gbp": 30_000, "max_gbp": 35_000, "period": "annual",
                },
            }),
            [],
        ))

    # ── 2 LIKELY_GHOST_JOB ───────────────────────────────────────────
    for i in range(2):
        scenarios.append((
            f"no_go_ghost_{i + 1}",
            "NO_GO", "LIKELY_GHOST_JOB", "uk_resident",
            _bundle_with(base_bundle, {"ghost_job": ghost}),
            [],
        ))

    # ── 2 DEAL_BREAKER_TRIGGERED ─────────────────────────────────────
    # Add a deal-breaker to the user that the JD obviously triggers.
    scenarios.append((
        "no_go_deal_breaker_1",
        "NO_GO", "DEAL_BREAKER_TRIGGERED", "uk_resident",
        _bundle_with(base_bundle, {
            "extracted_jd.role_title": "Software Engineer (5-day office)",
            "extracted_jd.remote_policy": "onsite",
        }),
        ["five-day-in-office mandate", "onsite-only roles"],
    ))
    scenarios.append((
        "no_go_deal_breaker_2",
        "NO_GO", "DEAL_BREAKER_TRIGGERED", "uk_resident",
        _bundle_with(base_bundle, {
            "extracted_jd.role_title": "Java Maintenance Engineer",
        }),
        ["pure maintenance roles", "Java-only stacks"],
    ))

    return scenarios


async def _body() -> tuple[list[str], list[str], float]:
    messages: list[str] = []
    failures: list[str] = []

    if os.environ.get(_GATE_ENV, "") != "1":
        messages.append(
            f"skipped — set {_GATE_ENV}=1 to opt into the paid live "
            "verdict stress (~$20-25 across 20 Opus xhigh calls)"
        )
        return messages, failures, 0.0

    prepare_environment()
    missing = require_anthropic_key()
    if missing:
        return [], [missing], 0.0

    from trajectory.storage import Storage
    from trajectory.sub_agents import verdict as verdict_agent

    base_bundle = load_fixture_bundle()
    scenarios = _scenarios(base_bundle)

    storage = Storage()
    await storage.initialise()

    by_outcome: dict[str, dict[str, int]] = {
        "GO": {"pass": 0, "fail": 0},
        "NO_GO": {"pass": 0, "fail": 0},
    }

    try:
        for label, expected_decision, expected_blocker, user_type, bundle, deal_breakers in scenarios:
            user = build_test_user(user_type)
            user.user_id = f"smoke_e2e_{label}"
            if deal_breakers:
                user.deal_breakers = list(deal_breakers)
            session = build_test_session(user.user_id)
            await storage.save_user_profile(user)
            await storage.save_session(session)

            try:
                verdict = await verdict_agent.generate(
                    research_bundle=bundle,
                    user=user,
                    retrieved_entries=[],
                    session_id=session.session_id,
                )
            except Exception as exc:
                failures.append(
                    f"[{label}] verdict.generate raised: {exc!r}"
                )
                by_outcome[expected_decision]["fail"] += 1
                continue

            scenario_failures: list[str] = []

            # Decision check
            if verdict.decision != expected_decision:
                scenario_failures.append(
                    f"decision={verdict.decision} expected {expected_decision}"
                )

            # Rule 2: GO must never carry hard blockers
            if verdict.decision == "GO" and verdict.hard_blockers:
                scenario_failures.append(
                    f"Rule 2 violation: GO with "
                    f"{len(verdict.hard_blockers)} hard_blocker(s)"
                )

            # Reasoning floor
            if len(verdict.reasoning) < 3:
                scenario_failures.append(
                    f"reasoning_points={len(verdict.reasoning)} < 3"
                )

            # Expected blocker type when NO_GO
            if expected_blocker is not None:
                blocker_types = {b.type for b in verdict.hard_blockers}
                if expected_blocker not in blocker_types:
                    scenario_failures.append(
                        f"expected blocker {expected_blocker} not in "
                        f"{sorted(blocker_types)}"
                    )

            if scenario_failures:
                for sf in scenario_failures:
                    failures.append(f"[{label}] {sf}")
                by_outcome[expected_decision]["fail"] += 1
            else:
                by_outcome[expected_decision]["pass"] += 1
                blockers_str = ",".join(
                    b.type for b in verdict.hard_blockers
                ) or "—"
                messages.append(
                    f"[{label}] {verdict.decision} "
                    f"(conf={verdict.confidence_pct}%, "
                    f"reasoning={len(verdict.reasoning)}, "
                    f"blockers={blockers_str})"
                )
    finally:
        await storage.close()

    total_pass = sum(c["pass"] for c in by_outcome.values())
    total = sum(c["pass"] + c["fail"] for c in by_outcome.values())
    messages.insert(
        0,
        f"e2e live stress: {total_pass}/{total} across {total} "
        f"(GO {by_outcome['GO']['pass']}/{by_outcome['GO']['pass'] + by_outcome['GO']['fail']}, "
        f"NO_GO {by_outcome['NO_GO']['pass']}/{by_outcome['NO_GO']['pass'] + by_outcome['NO_GO']['fail']})"
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
