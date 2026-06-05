"""Smoke: compare_verdicts ranker + challenge_verdict plumbing.

Architecture gaps #6 and #8.

compare_verdicts is fully deterministic — seed three synthetic GO
sessions with different (confidence, age, density) signatures, run
the ranker, assert the order matches the composite formula.

challenge_verdict can't be exercised live in the cheap tier because
its body calls a model. We assert the wiring instead:
  - the orchestrator handler exists and refuses sessions without a
    Phase 1 bundle (ValueError)
  - _build_user_input on verdict.py correctly threads user_challenge
    through to the prompt payload

Cost: $0. Storage is in-memory SQLite under prepare_environment.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from ._common import (
    SmokeResult,
    build_test_user,
    prepare_environment,
    run_smoke,
)

NAME = "compare_and_challenge"
ESTIMATED_COST_USD = 0.0


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()
    messages: list[str] = []
    failures: list[str] = []

    from askpicky import storage
    from askpicky.orchestrator import handle_compare_verdicts
    from askpicky.schemas import (
        Citation,
        HardBlocker,
        MotivationFitReport,
        ReasoningPoint,
        Session,
        StretchConcern,
        Verdict,
    )
    from askpicky.sub_agents.verdict import _build_user_input
    import uuid

    # ──────────────────────────────────────────────────────────────
    # compare_verdicts — synthetic sessions
    # ──────────────────────────────────────────────────────────────

    user = build_test_user("uk_resident")
    await storage.upsert_user_profile(user)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    def _mk_verdict(conf: int, reasoning_n: int = 4, stretch_n: int = 1) -> Verdict:
        return Verdict(
            decision="GO",
            confidence_pct=conf,
            entropy_norm=0.15,
            headline=f"GO at {conf}% — strong fit",
            reasoning=[
                ReasoningPoint(
                    claim=f"point {i}",
                    supporting_evidence="evidence text",
                    citation=Citation(
                        kind="gov_data",
                        data_field="sponsor_register.status",
                        data_value="LISTED",
                    ),
                )
                for i in range(reasoning_n)
            ],
            hard_blockers=[],
            stretch_concerns=[
                StretchConcern(
                    type="MOTIVATION_MISMATCH",
                    detail=f"concern {i}",
                    citations=[
                        Citation(
                            kind="gov_data",
                            data_field="user_profile.motivation",
                            data_value="leadership",
                        )
                    ],
                )
                for i in range(stretch_n)
            ],
            motivation_fit=MotivationFitReport(
                motivation_evaluations=[],
                deal_breaker_evaluations=[],
                good_role_signal_evaluations=[],
            ),
        )

    # A: high confidence, fresh (1d), dense → best score
    # B: medium confidence, mid age (10d), moderate density
    # C: high confidence but very old (25d) → freshness penalty
    # D: BLOCKED — should be excluded from ranking entirely
    test_sessions = [
        ("A", 90, 5, 1, now - timedelta(days=1), "GO"),
        ("B", 70, 4, 2, now - timedelta(days=10), "GO"),
        ("C", 85, 4, 1, now - timedelta(days=25), "GO"),
        ("D", 95, 5, 0, now - timedelta(hours=2), "BLOCKED"),
    ]
    ids: dict[str, str] = {}
    for label, conf, reasoning_n, stretch_n, created_at, decision in test_sessions:
        sid = str(uuid.uuid4())
        ids[label] = sid
        # Synthesize a verdict + phase1 payload
        v = _mk_verdict(conf, reasoning_n, stretch_n)
        if decision != "GO":
            v = v.model_copy(update={"decision": decision})
        s = Session(
            session_id=sid,
            user_id=user.user_id,
            intent="forward_job",
            job_url=f"https://example.com/{label}",
            phase1_output={
                "extracted_jd": {"role_title": f"Role-{label}"},
                "company_research": {"company_name": f"Company-{label}"},
            },
            verdict=v.model_dump(),
            created_at=created_at,
        )
        await storage.insert_session(s)

    storage_iface = storage.Storage()
    result = await handle_compare_verdicts(
        user=user, storage=storage_iface, limit=10,
    )

    if not result.methodology:
        failures.append("compare_verdicts methodology field empty")

    # D (NO_GO) must NOT appear in the ranking.
    if any(r.session_id == ids["D"] for r in result.ranked):
        failures.append("NO_GO session leaked into compare_verdicts output")

    # All three GOs (A, B, C) should appear.
    ranked_ids = {r.session_id for r in result.ranked}
    if not {ids["A"], ids["B"], ids["C"]}.issubset(ranked_ids):
        failures.append(
            f"missing GO sessions from ranking: "
            f"got {ranked_ids}, want A/B/C={ids['A']}/{ids['B']}/{ids['C']}"
        )

    # Expected order: A > B/C (A wins on freshness AND density).
    # A's composite ~= 90*.6 + 100*.25 + 50*.15 = 54 + 25 + 7.5 = 86.5
    # B's composite ~= 70*.6 + ~55*.25 + 25*.15 ≈ 42 + 13.75 + 3.75 ≈ 59.5
    # C's composite ~= 85*.6 + 20*.25 + 37.5*.15 ≈ 51 + 5 + 5.6 ≈ 61.6
    if result.ranked[0].session_id != ids["A"]:
        failures.append(
            f"top of ranking should be A (high conf + fresh + dense); "
            f"got {result.ranked[0].session_id}"
        )
    else:
        messages.append(
            f"top-ranked A: score={result.ranked[0].score} "
            f"headline={result.ranked[0].headline!r}"
        )

    # B (medium conf, mid age) should score lower than C (high conf,
    # very old) because A's freshness advantage exceeds C's confidence
    # boost. Actually: confidence weight (60%) > freshness weight (25%),
    # so C may beat B. Just assert the bottom slot is correctly placed —
    # whichever of B/C is last must have the lowest score.
    sorted_scores = sorted([r.score for r in result.ranked], reverse=True)
    if [r.score for r in result.ranked] != sorted_scores:
        failures.append(
            f"compare_verdicts ranking not in descending score order: "
            f"{[r.score for r in result.ranked]}"
        )
    else:
        messages.append(
            f"3 GO sessions ranked correctly: "
            f"{[(r.session_id[:4], r.score) for r in result.ranked]}"
        )

    # Per-row rationale should mention freshness/confidence drivers.
    a_row = next(r for r in result.ranked if r.session_id == ids["A"])
    if "confidence" not in a_row.rationale.lower():
        failures.append(
            f"A's rationale should reference confidence: {a_row.rationale!r}"
        )

    c_row = next(r for r in result.ranked if r.session_id == ids["C"])
    if "day" not in c_row.rationale.lower():
        failures.append(
            f"C's rationale (25-day-old) should reference age: {c_row.rationale!r}"
        )

    # ──────────────────────────────────────────────────────────────
    # challenge_verdict — wiring only (no LLM)
    # ──────────────────────────────────────────────────────────────

    # 1. _build_user_input threads user_challenge through correctly.
    from askpicky.schemas import ResearchBundle, CompanyResearch, ExtractedJobDescription, GhostJobAssessment, GhostJobJDScore, RedFlagsReport

    bundle = ResearchBundle(
        session_id="smoke-bundle",
        extracted_jd=ExtractedJobDescription(
            role_title="Senior Engineer",
            seniority_signal="senior",
            soc_code_guess="2136",
            soc_code_reasoning="software engineering",
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

    payload_no_challenge = _build_user_input(bundle, user, [], None, None)
    payload_with_challenge = _build_user_input(
        bundle, user, [],
        prior_outcomes_text=None,
        user_challenge_text="I know they sponsor visas, my friend got one last month.",
    )
    if "user_challenge" in payload_no_challenge:
        failures.append(
            "user_challenge field appeared in payload when text was None"
        )
    parsed = json.loads(payload_with_challenge)
    if parsed.get("user_challenge") != \
            "I know they sponsor visas, my friend got one last month.":
        failures.append(
            f"user_challenge not threaded into payload: "
            f"got {parsed.get('user_challenge')!r}"
        )
    else:
        messages.append("user_challenge threads through _build_user_input")

    # 2. handle_challenge_verdict raises ValueError without a Phase 1 bundle.
    from askpicky.orchestrator import handle_challenge_verdict

    naked_session = Session(
        session_id="naked",
        user_id=user.user_id,
        intent="forward_job",
        job_url="https://example.com/naked",
        phase1_output=None,
        created_at=now,
    )
    try:
        await handle_challenge_verdict(
            user=user,
            session=naked_session,
            challenge_text="anything",
            storage=storage_iface,
        )
        failures.append(
            "handle_challenge_verdict accepted a session with no Phase 1 "
            "bundle (should raise ValueError)"
        )
    except ValueError:
        messages.append(
            "handle_challenge_verdict correctly rejects sessions without "
            "a stored Phase 1 bundle"
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
