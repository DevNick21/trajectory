"""Smoke: Phase 1 signal weights — architecture gap #7.

Verifies:
- 8 pillars present per user_type.
- Each row sums to ~1.0 (allowing tiny float rounding drift).
- UK residents have zero weight on sponsor_register + soc_check.
- Visa holders weight sponsor + SOC well above any other pillar.
- SOC adjustments shift weights AND preserve the sum-to-1 invariant.
- Verdict's _build_user_input includes signal_weights in the payload.

Cost: $0.
"""

from __future__ import annotations

import asyncio
import json

from ._common import (
    SmokeResult,
    build_test_user,
    prepare_environment,
    run_smoke,
)

NAME = "signal_weights"
ESTIMATED_COST_USD = 0.0


_EXPECTED_PILLARS = {
    "sponsor_register",
    "soc_check",
    "companies_house_distress",
    "gazette",
    "ghost_job",
    "red_flags",
    "agency_posting",
    "motivation_fit",
}


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()
    messages: list[str] = []
    failures: list[str] = []

    from askpicky.signal_weights import get_signal_weights

    # Layer 1: defaults per user_type
    for user_type in ("visa_holder", "uk_resident"):
        weights = get_signal_weights(user_type)  # type: ignore[arg-type]

        if set(weights.keys()) != _EXPECTED_PILLARS:
            failures.append(
                f"{user_type}: pillar set mismatch — got {set(weights.keys())}, "
                f"want {_EXPECTED_PILLARS}"
            )
            continue

        total = sum(weights.values())
        if not (0.98 <= total <= 1.02):
            failures.append(
                f"{user_type}: weights sum to {total:.4f}, expected ~1.0"
            )

        messages.append(
            f"{user_type}: sum={total:.4f}, top-3="
            f"{sorted(weights.items(), key=lambda kv: kv[1], reverse=True)[:3]}"
        )

    # Layer 2: UK residents must zero out sponsor + SOC pillars
    uk = get_signal_weights("uk_resident")
    if uk["sponsor_register"] != 0.0 or uk["soc_check"] != 0.0:
        failures.append(
            f"uk_resident must have zero weight on sponsor+SOC; "
            f"got sponsor={uk['sponsor_register']} soc={uk['soc_check']}"
        )
    else:
        messages.append("uk_resident sponsor + SOC weights correctly zero")

    # Layer 3: visa holders should weight sponsor+SOC > 0.4 combined
    visa = get_signal_weights("visa_holder")
    combined = visa["sponsor_register"] + visa["soc_check"]
    if combined < 0.4:
        failures.append(
            f"visa_holder sponsor+SOC combined weight too low: {combined:.3f} "
            f"(want >= 0.4)"
        )
    elif visa["sponsor_register"] <= visa["companies_house_distress"]:
        failures.append(
            f"visa_holder sponsor_register should outweigh CH distress; "
            f"got sponsor={visa['sponsor_register']} ch={visa['companies_house_distress']}"
        )
    else:
        messages.append(
            f"visa_holder sponsor+SOC combined = {combined:.3f} "
            f"(dominant as expected)"
        )

    # Layer 4: SOC 2136 adjustment shifts agency_posting up
    visa_default = get_signal_weights("visa_holder")
    visa_se = get_signal_weights("visa_holder", soc_code="2136")
    if visa_se["agency_posting"] <= visa_default["agency_posting"]:
        failures.append(
            "SOC 2136 should bump agency_posting weight (software-eng has "
            f"more agency noise); default={visa_default['agency_posting']} "
            f"se={visa_se['agency_posting']}"
        )
    else:
        messages.append(
            f"SOC 2136 bumps agency_posting: "
            f"{visa_default['agency_posting']:.3f} -> "
            f"{visa_se['agency_posting']:.3f}"
        )

    # SOC-adjusted rows must still sum to ~1.0
    se_total = sum(visa_se.values())
    if not (0.98 <= se_total <= 1.02):
        failures.append(
            f"SOC-adjusted weights drift from sum=1: got {se_total:.4f}"
        )

    # Layer 5: verdict payload includes signal_weights
    from askpicky.sub_agents.verdict import _build_user_input
    from askpicky.schemas import (
        CompanyResearch,
        ExtractedJobDescription,
        GhostJobAssessment,
        GhostJobJDScore,
        RedFlagsReport,
        ResearchBundle,
    )
    from datetime import datetime, timezone

    user = build_test_user("visa_holder")
    bundle = ResearchBundle(
        session_id="weights-smoke",
        extracted_jd=ExtractedJobDescription(
            role_title="Senior Software Engineer",
            seniority_signal="senior",
            soc_code_guess="2136",
            soc_code_reasoning="...",
            location="London",
            remote_policy="hybrid",
            required_skills=["python"],
            posting_platform="company_site",
            hiring_manager_named=False,
            jd_text_full="...",
            specificity_signals=[],
            vagueness_signals=[],
        ),
        company_research=CompanyResearch(
            company_name="Acme",
            scraped_pages=[],
            careers_page_url=None,
        ),
        ghost_job=GhostJobAssessment(
            probability="LIKELY_REAL", signals=[], confidence="HIGH",
            raw_jd_score=GhostJobJDScore(
                named_hiring_manager=0.0,
                specific_duty_bullets=1.0,
                specific_tech_stack=1.0,
                specific_team_context=1.0,
                specific_success_metrics=1.0,
                specificity_score=4.0,
                specificity_signals=[],
                vagueness_signals=[],
            ),
        ),
        red_flags=RedFlagsReport(flags=[], checked=True),
        bundle_completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    payload = _build_user_input(bundle, user, [], None, None)
    parsed = json.loads(payload)

    if "signal_weights" not in parsed:
        failures.append(
            "signal_weights missing from verdict payload — gap #7 "
            "plumbing broken"
        )
    elif set(parsed["signal_weights"].keys()) != _EXPECTED_PILLARS:
        failures.append(
            f"verdict payload signal_weights pillar set mismatch: "
            f"{set(parsed['signal_weights'].keys())}"
        )
    else:
        messages.append(
            f"verdict payload carries signal_weights with "
            f"{len(parsed['signal_weights'])} pillars"
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
