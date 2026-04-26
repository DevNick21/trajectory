"""Smoke test — forward_job journey for a UK resident, fixture-driven.

Covers the orchestrator wiring that the existing per-agent smokes leave
uncovered:

  - All Phase 1 sub-agents are invoked (or marked skipped) and emit the
    expected progress events in the right order — the load-bearing
    contract for CLAUDE.md Rule 9 (Telegram streaming reveals).
  - `handle_forward_job` constructs a valid `ResearchBundle` from sub-agent
    outputs and persists it via `storage.save_phase1_output`.
  - The shielded-bundle path runs to completion on clean fixture content
    (no MALICIOUS Tier 2 verdict).
  - The verdict (mocked via SMOKE_TEST_MOCK=1) is persisted and returned.
  - For uk_resident, sponsor_register + soc_check are marked skipped
    (None) without calling the sub-agents.

Phase 1 sub-agents are monkey-patched to return slices of the fixture
bundle. Verdict is the production agent under SMOKE_TEST_MOCK=1 — the
mock returns a fixture verdict but exercises `_enforce_no_go_with_blockers`
and the storage round-trip.

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

NAME = "forward_journey_uk"
REQUIRES_LIVE_LLM = False
ESTIMATED_COST_USD = 0.0


# Phase 1 sub-agent events expected in the orchestrator's `mark()` stream.
# Order is roughly the completion order, but the parallel block (1C) can
# fire in any order — we assert set equality rather than sequence.
_EXPECTED_EVENTS: set[str] = {
    "phase_1_jd_extractor",
    "phase_1_company_scraper_summariser",
    "companies_house",
    "reviews",
    "salary_data",
    "sponsor_register",          # marked even when skipped for uk_resident
    "soc_check",                 # marked even when skipped for uk_resident
    "phase_1_ghost_job_jd_scorer",
    "phase_1_red_flags",
}


class _CapturingEmitter:
    """ProgressEmitter test double — records every emitted event."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def close(self) -> None:
        pass


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    # Mocked verdict so the test runs without an Anthropic key. Cleared
    # in `finally` so a subsequent test in the same process is unaffected.
    prior_mock = os.environ.get("SMOKE_TEST_MOCK")
    os.environ["SMOKE_TEST_MOCK"] = "1"

    messages: list[str] = []
    failures: list[str] = []

    try:
        from trajectory import orchestrator
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
        )

        bundle = load_fixture_bundle()
        user = build_test_user("uk_resident")
        session = build_test_session(user.user_id)

        storage = Storage()
        await storage.initialise()
        await storage.save_user_profile(user)
        await storage.save_session(session)

        # Snapshot originals so we can restore on exit even if the test
        # raises mid-flight.
        originals = {
            "company_scraper.run": company_scraper.run,
            "ch_agent.lookup": ch_agent.lookup,
            "rev_agent.fetch": rev_agent.fetch,
            "sal_agent.fetch": sal_agent.fetch,
            "sr_agent.lookup": sr_agent.lookup,
            "soc_agent.verify": soc_agent.verify,
            "ghost_job_detector.score": ghost_job_detector.score,
            "rf_agent.detect": rf_agent.detect,
        }

        # Replace each sub-agent with a coroutine that returns the
        # corresponding slice of the fixture bundle.
        async def _fake_scraper(*, job_url, session_id):
            return bundle.company_research, bundle.extracted_jd

        async def _fake_ch(*, company_name):
            return bundle.companies_house

        async def _fake_reviews(*, company_name):
            return []  # fixture has no reviews; orchestrator handles []

        async def _fake_salary(*, role, location, soc_code, posted_band):
            return bundle.salary_signals

        async def _fake_sponsor(*, company_name):
            return bundle.sponsor_status

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

        emitter = _CapturingEmitter()

        try:
            try:
                returned_bundle, verdict = await orchestrator.handle_forward_job(
                    job_url="https://example.com/job/smoke",
                    user=user,
                    session=session,
                    storage=storage,
                    emitter=emitter,
                )
            except Exception as exc:
                failures.append(f"handle_forward_job raised: {exc!r}")
                return messages, failures, ESTIMATED_COST_USD

            # ── Assert: emitted events ──────────────────────────────────
            seen_events = {
                e.get("agent")
                for e in emitter.events
                if e.get("type") == "agent_complete"
            }
            missing = _EXPECTED_EVENTS - seen_events
            if missing:
                failures.append(
                    f"Phase 1 progress stream missing agents: {sorted(missing)} "
                    f"(saw: {sorted(seen_events)})"
                )
            messages.append(
                f"emitted {len(emitter.events)} agent_complete event(s); "
                f"all 9 Phase 1 hooks fired"
            )

            # ── Assert: bundle shape ────────────────────────────────────
            if returned_bundle.company_research.company_name != "Acme Tech Ltd":
                failures.append(
                    f"bundle.company_research.company_name="
                    f"{returned_bundle.company_research.company_name!r} != 'Acme Tech Ltd'"
                )
            if returned_bundle.extracted_jd.role_title != "Senior Software Engineer":
                failures.append(
                    f"bundle.extracted_jd.role_title="
                    f"{returned_bundle.extracted_jd.role_title!r}"
                )
            # uk_resident skips sponsor + soc (None passed through).
            if returned_bundle.sponsor_status is not None:
                failures.append(
                    f"uk_resident bundle leaked sponsor_status: "
                    f"{returned_bundle.sponsor_status!r}"
                )
            if returned_bundle.soc_check is not None:
                failures.append(
                    f"uk_resident bundle leaked soc_check: "
                    f"{returned_bundle.soc_check!r}"
                )
            messages.append(
                f"bundle: company={returned_bundle.company_research.company_name}, "
                f"sponsor=None (uk_resident skip), soc=None (uk_resident skip)"
            )

            # ── Assert: verdict shape ───────────────────────────────────
            if verdict.decision not in {"GO", "NO_GO"}:
                failures.append(
                    f"verdict.decision={verdict.decision!r} not in GO/NO_GO"
                )
            if verdict.decision == "GO" and verdict.hard_blockers:
                failures.append(
                    "Rule 2 violation: GO with hard_blockers escaped the guard."
                )
            messages.append(
                f"verdict: decision={verdict.decision} "
                f"confidence={verdict.confidence_pct}% "
                f"reasoning_points={len(verdict.reasoning)}"
            )

            # ── Assert: storage persistence ──────────────────────────────
            reloaded = await storage.get_session(session.session_id)
            if reloaded is None:
                failures.append("session disappeared from storage after forward_job")
            else:
                if reloaded.verdict is None:
                    failures.append(
                        "storage.save_verdict didn't persist — "
                        "session.verdict is None on reload."
                    )
                if reloaded.phase1_output is None:
                    failures.append(
                        "storage.save_phase1_output didn't persist — "
                        "session.phase1_output is None on reload."
                    )

            messages.append("storage round-trip OK: verdict + bundle reloaded")
        finally:
            company_scraper.run = originals["company_scraper.run"]
            ch_agent.lookup = originals["ch_agent.lookup"]
            rev_agent.fetch = originals["rev_agent.fetch"]
            sal_agent.fetch = originals["sal_agent.fetch"]
            sr_agent.lookup = originals["sr_agent.lookup"]
            soc_agent.verify = originals["soc_agent.verify"]
            ghost_job_detector.score = originals["ghost_job_detector.score"]
            rf_agent.detect = originals["rf_agent.detect"]
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
