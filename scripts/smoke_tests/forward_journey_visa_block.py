"""Smoke test — forward_job journey for a visa_holder, sponsor missing.

This is the differentiator path from the Problem Statement: a visa-holder
forwards a role at an unlisted-sponsor company. Two protections must hold:

  1. The bundle carries `SponsorStatus.status == NOT_LISTED` end-to-end.
     If the orchestrator drops the visa_holder branch (Rule 2 of
     CLAUDE.md), this is where it shows up.

  2. CLAUDE.md Rule 2's programmatic guard (`_enforce_no_go_with_blockers`
     in sub_agents/verdict.py:138) flips a `GO` verdict to `NO_GO` when
     any hard blocker is present. We patch `_mock_verdict` to return an
     intentionally-inconsistent `GO + hard_blocker(NOT_ON_SPONSOR_REGISTER)`
     and assert the guard catches it.

Phase 1 sub-agents are monkey-patched to fixture data with
`sponsor_register.lookup` overridden to return NOT_LISTED. Verdict is
mocked via SMOKE_TEST_MOCK=1; the mock body is replaced with a
deliberately-wrong Verdict so the test exercises the guard.

Cost: $0 (no live LLM calls).
"""

from __future__ import annotations

import os
from typing import Any

from ._common import (
    SmokeResult,
    build_test_session,
    build_test_user,
    load_fixture_bundle,
    prepare_environment,
    run_smoke,
)

NAME = "forward_journey_visa_block"
REQUIRES_LIVE_LLM = False
ESTIMATED_COST_USD = 0.0


class _CapturingEmitter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def close(self) -> None:
        pass


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    prior_mock = os.environ.get("SMOKE_TEST_MOCK")
    os.environ["SMOKE_TEST_MOCK"] = "1"

    messages: list[str] = []
    failures: list[str] = []

    try:
        from trajectory import orchestrator
        from trajectory.schemas import (
            Citation,
            HardBlocker,
            MotivationFitReport,
            ReasoningPoint,
            SponsorStatus,
            Verdict,
        )
        from trajectory.storage import Storage
        from trajectory.sub_agents import (
            companies_house as ch_agent,
            company_scraper,
            ghost_job_detector,
            red_flags as rf_agent,
            reviews as rev_agent,
            salary_data as sal_agent,
            soc_check as soc_agent,
            sponsor_register as sr_agent,
            verdict as verdict_module,
        )

        bundle = load_fixture_bundle()
        user = build_test_user("visa_holder")
        session = build_test_session(user.user_id)

        storage = Storage()
        await storage.initialise()
        await storage.save_user_profile(user)
        await storage.save_session(session)

        # Force sponsor_register to NOT_LISTED for this run.
        not_listed = SponsorStatus(
            status="NOT_LISTED",
            matched_name=None,
            rating=None,
            visa_routes=[],
            last_register_update=bundle.sponsor_status.last_register_update,
            source_status="OK",
        )

        # Synthetic, deliberately-wrong verdict: decision=GO with a
        # hard_blocker present. The orchestrator's
        # _enforce_no_go_with_blockers guard MUST flip this to NO_GO.
        wrong_citation = Citation(
            kind="gov_data",
            data_field="sponsor_register.status",
            data_value="NOT_LISTED",
        )
        wrong_verdict = Verdict(
            decision="GO",
            confidence_pct=85,
            headline="Apply - sponsor visa pathway clear (this is wrong on purpose).",
            reasoning=[
                ReasoningPoint(
                    claim="Synthetic claim 1.",
                    supporting_evidence="fixture",
                    citation=wrong_citation,
                ),
                ReasoningPoint(
                    claim="Synthetic claim 2.",
                    supporting_evidence="fixture",
                    citation=wrong_citation,
                ),
                ReasoningPoint(
                    claim="Synthetic claim 3.",
                    supporting_evidence="fixture",
                    citation=wrong_citation,
                ),
            ],
            hard_blockers=[
                HardBlocker(
                    type="NOT_ON_SPONSOR_REGISTER",
                    detail=(
                        f"{bundle.company_research.company_name} is not on the "
                        "Home Office sponsor register; visa_holder cannot accept."
                    ),
                    citation=wrong_citation,
                ),
            ],
            stretch_concerns=[],
            motivation_fit=MotivationFitReport(
                motivation_evaluations=[],
                deal_breaker_evaluations=[],
                good_role_signal_evaluations=[],
            ),
        )

        # Patch sub-agents to fixture slices; sponsor swapped to NOT_LISTED.
        originals = {
            "company_scraper.run": company_scraper.run,
            "ch_agent.lookup": ch_agent.lookup,
            "rev_agent.fetch": rev_agent.fetch,
            "sal_agent.fetch": sal_agent.fetch,
            "sr_agent.lookup": sr_agent.lookup,
            "soc_agent.verify": soc_agent.verify,
            "ghost_job_detector.score": ghost_job_detector.score,
            "rf_agent.detect": rf_agent.detect,
            "verdict_module._mock_verdict": verdict_module._mock_verdict,
        }

        async def _fake_scraper(*, job_url, session_id, on_jd_extracted=None):
            if on_jd_extracted is not None:
                await on_jd_extracted()
            return bundle.company_research, bundle.extracted_jd

        async def _fake_ch(*, company_name):
            return bundle.companies_house

        async def _fake_reviews(*, company_name):
            return []

        async def _fake_salary(*, role, location, soc_code, posted_band):
            return bundle.salary_signals

        async def _fake_sponsor(*, company_name):
            return not_listed

        async def _fake_soc(*, jd, user):
            return bundle.soc_check

        async def _fake_ghost(*, jd, company_research, companies_house, job_url, session_id):
            return bundle.ghost_job

        async def _fake_red_flags(*, company_research, companies_house, reviews, session_id):
            return bundle.red_flags

        company_scraper.run = _fake_scraper
        ch_agent.lookup = _fake_ch
        rev_agent.fetch = _fake_reviews
        sal_agent.fetch = _fake_salary
        sr_agent.lookup = _fake_sponsor
        soc_agent.verify = _fake_soc
        ghost_job_detector.score = _fake_ghost
        rf_agent.detect = _fake_red_flags
        verdict_module._mock_verdict = lambda user, bundle: wrong_verdict

        emitter = _CapturingEmitter()

        try:
            try:
                returned_bundle, verdict = await orchestrator.handle_forward_job(
                    job_url="https://example.com/job/visa-smoke",
                    user=user,
                    session=session,
                    storage=storage,
                    emitter=emitter,
                )
            except Exception as exc:
                failures.append(f"handle_forward_job raised: {exc!r}")
                return messages, failures, ESTIMATED_COST_USD

            # ── Assert: NOT_LISTED carried through ──────────────────────
            if returned_bundle.sponsor_status is None:
                failures.append(
                    "visa_holder bundle has sponsor_status=None — "
                    "the visa branch (Rule 2) was skipped."
                )
            elif returned_bundle.sponsor_status.status != "NOT_LISTED":
                failures.append(
                    f"sponsor_status.status="
                    f"{returned_bundle.sponsor_status.status!r} "
                    "expected NOT_LISTED."
                )
            else:
                messages.append(
                    "bundle.sponsor_status.status=NOT_LISTED carried through"
                )

            if returned_bundle.soc_check is None:
                failures.append(
                    "visa_holder bundle has soc_check=None — "
                    "soc branch should have run for visa_holder."
                )

            # ── Assert: Rule 2 flip fired ───────────────────────────────
            if verdict.decision != "NO_GO":
                failures.append(
                    f"Rule 2 guard didn't flip GO+hard_blocker — "
                    f"decision={verdict.decision!r} "
                    f"hard_blockers={[b.type for b in verdict.hard_blockers]}"
                )
            else:
                messages.append(
                    "Rule 2 guard flipped GO+hard_blocker to NO_GO as expected"
                )

            blocker_types = {b.type for b in verdict.hard_blockers}
            if "NOT_ON_SPONSOR_REGISTER" not in blocker_types:
                failures.append(
                    f"verdict.hard_blockers missing NOT_ON_SPONSOR_REGISTER: "
                    f"{sorted(blocker_types)}"
                )
            else:
                messages.append(
                    "verdict.hard_blockers includes NOT_ON_SPONSOR_REGISTER"
                )

            # ── Assert: confidence was downgraded by the guard ──────────
            # _enforce_no_go_with_blockers caps confidence at 60 on flip.
            if verdict.decision == "NO_GO" and verdict.confidence_pct > 60:
                failures.append(
                    f"flipped verdict still has confidence_pct="
                    f"{verdict.confidence_pct} > 60 — guard didn't downgrade."
                )
        finally:
            company_scraper.run = originals["company_scraper.run"]
            ch_agent.lookup = originals["ch_agent.lookup"]
            rev_agent.fetch = originals["rev_agent.fetch"]
            sal_agent.fetch = originals["sal_agent.fetch"]
            sr_agent.lookup = originals["sr_agent.lookup"]
            soc_agent.verify = originals["soc_agent.verify"]
            ghost_job_detector.score = originals["ghost_job_detector.score"]
            rf_agent.detect = originals["rf_agent.detect"]
            verdict_module._mock_verdict = originals["verdict_module._mock_verdict"]
            await storage.close()
    finally:
        if prior_mock is None:
            os.environ.pop("SMOKE_TEST_MOCK", None)
        else:
            os.environ["SMOKE_TEST_MOCK"] = prior_mock

    return messages, failures, ESTIMATED_COST_USD


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
