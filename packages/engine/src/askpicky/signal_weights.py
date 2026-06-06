"""Phase 1 signal weights.

Deterministic signal weights keep verdict reasoning consistent across similar
jobs and create a surface for outcome-informed calibration.

This module returns a deterministic per-pillar weight map keyed by
`(user_type, soc_code)`. The verdict consumes it as `signal_weights`
in the user payload, with explicit guidance in the prompt to use the
weights as PRIORS — i.e. a pillar weighted 0.30 should move
confidence ~3x as much as one weighted 0.10. The weights don't
multiply into a hard score; they keep reasoning calibrated.

Future calibration:
- Outcome-driven re-weighting can nudge weights when reported outcomes
  contradict a pillar's prediction. For example, if
  `sponsor_register=LISTED` correlates with `outcome=ghosted`, the sponsor
  pillar can drop. The weights table is structured for storage-backed loading
  keyed by the same tuple.

Defaults are calibrated to "what AskPicky has consistently treated
as load-bearing in the verdict prompt". Update them when outcome data
justifies a change.
"""

from __future__ import annotations

from typing import Literal, Optional

UserType = Literal["uk_resident", "visa_holder"]

# Pillar names. These match the keys the verdict prompt references.
# Adding a new pillar requires a row in every weights table below.
PILLARS = (
    "sponsor_register",
    "companies_house_distress",
    "soc_check",
    "ghost_job",
    "gazette",
    "red_flags",
    "agency_posting",
    "motivation_fit",
)


# Default weights — what AskPicky has consistently weighted in the
# verdict prompt. Each row sums to ~1.0 so the verdict can interpret
# weights as relative priors.
_DEFAULT_WEIGHTS: dict[UserType, dict[str, float]] = {
    "visa_holder": {
        # For visa holders, sponsor_register is the load-bearing
        # gate — no licence = no visa, regardless of every other
        # signal. SOC check matters too but the gate is binary
        # (below threshold or not), so it gets less prior weight
        # than the more nuanced sponsor analysis.
        "sponsor_register": 0.28,
        "soc_check": 0.18,
        "companies_house_distress": 0.13,
        "gazette": 0.12,
        "ghost_job": 0.10,
        "red_flags": 0.08,
        "agency_posting": 0.06,
        "motivation_fit": 0.05,
    },
    "uk_resident": {
        # No visa gate; the analysis lives entirely in company
        # health + role authenticity + motivation fit. Companies
        # House distress + Gazette + ghost-job collectively
        # dominate.
        "sponsor_register": 0.0,
        "soc_check": 0.0,
        "companies_house_distress": 0.25,
        "gazette": 0.20,
        "ghost_job": 0.18,
        "red_flags": 0.15,
        "agency_posting": 0.10,
        "motivation_fit": 0.12,
    },
}


# SOC-specific adjustments. Some occupations have systematically
# different signal profiles — e.g. SOC 2136 (software engineering)
# carries a lot of agency-posting noise; SOC 1135 (financial
# institution managers) is overwhelmingly in-house. The adjustments
# are additive on top of the base weights, then the row is
# renormalised to sum to 1.0.
_SOC_ADJUSTMENTS: dict[str, dict[str, float]] = {
    # Software engineering — agency posting noise is real
    "2136": {"agency_posting": +0.05, "ghost_job": +0.03, "motivation_fit": -0.02},
    # IT business analysts — similar
    "2135": {"agency_posting": +0.04, "ghost_job": +0.02},
    # Financial managers — agency rarer, signal noise lower
    "1135": {"agency_posting": -0.03, "companies_house_distress": +0.03},
    # Marketing — agency posts and ghost jobs both inflated
    "1132": {"agency_posting": +0.04, "ghost_job": +0.04},
}


def get_signal_weights(
    user_type: UserType,
    *,
    soc_code: Optional[str] = None,
) -> dict[str, float]:
    """Return weights for the eight pillars, keyed by name, summing to ~1.0.

    Used by the verdict prompt as priors for confidence calibration.

    Args:
        user_type: "uk_resident" or "visa_holder". Sponsor + SOC pillars
            zero out for UK residents.
        soc_code: optional SOC code from JD extraction. When present
            and matches a row in _SOC_ADJUSTMENTS, the weights are
            shifted accordingly then renormalised.
    """
    weights = dict(_DEFAULT_WEIGHTS[user_type])

    if soc_code and soc_code in _SOC_ADJUSTMENTS:
        for pillar, delta in _SOC_ADJUSTMENTS[soc_code].items():
            weights[pillar] = max(0.0, weights[pillar] + delta)

    # Renormalise so the row sums to 1.0. Pure additive shift can drift
    # the total above or below; the verdict's prior-reading is easier
    # to reason about when sum == 1.
    total = sum(weights.values())
    if total > 0:
        weights = {k: round(v / total, 4) for k, v in weights.items()}

    return weights
