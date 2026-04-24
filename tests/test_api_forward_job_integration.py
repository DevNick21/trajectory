"""Cross-surface integration test for POST /api/sessions/forward_job.

This differs from test_api_forward_job.py (which mocks the whole
`handle_forward_job` orchestrator). Here we let the REAL orchestrator
run and only mock the external-world seams — each Phase 1 sub-agent.
That exercises:

  - ProgressEmitter abstraction end-to-end (SSEEmitter →
    orchestrator.mark() → actual emit calls)
  - Every Phase 1 agent's mark() fires, in the right slot
  - asyncio.gather + run_ghost fallback behaviour (the bug fixed in
    a0a0961)
  - verdict.generate runs with the assembled ResearchBundle
  - Session is persisted with phase1_output + verdict for later
    GET /api/sessions/{id} reads
  - SSE frame sequence matches the Wave 4 contract
    (agent_complete × 9 + verdict + done)

This is Wave 11 of MIGRATION_PLAN.md. It's the test that would have
caught the `streamer`-reference NameError Wave 1 left behind.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trajectory.schemas import (
    CompanyResearch,
    ExtractedJobDescription,
    GhostJobAssessment,
    GhostJobJDScore,
    MotivationFitReport,
    RedFlagsReport,
    SalarySignals,
    UserProfile,
    Verdict,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _demo_user() -> UserProfile:
    n = _now()
    return UserProfile(
        user_id="demo-user-1",
        name="Demo",
        user_type="uk_resident",
        base_location="London",
        salary_floor=50_000,
        salary_target=70_000,
        search_started_date=date(2026, 1, 1),
        current_employment="EMPLOYED",
        created_at=n,
        updated_at=n,
    )


def _synthetic_company_research() -> CompanyResearch:
    return CompanyResearch(
        company_name="Acme Ltd",
        company_domain="acme.example.com",
        scraped_pages=[],
        culture_claims=[],
        tech_stack_signals=[],
        team_size_signals=[],
        recent_activity_signals=[],
        posted_salary_bands=[],
        policies={},
        careers_page_url=None,
        not_on_careers_page=False,
    )


def _synthetic_jd() -> ExtractedJobDescription:
    return ExtractedJobDescription(
        role_title="Senior Backend Engineer",
        seniority_signal="senior",
        soc_code_guess="2136",
        soc_code_reasoning="Software role.",
        salary_band=None,
        location="London",
        remote_policy="hybrid",
        required_skills=["Python", "AWS"],
        posted_date=date(2026, 4, 1),
        posting_platform="company_site",
        hiring_manager_named=True,
        hiring_manager_name="Alex",
        jd_text_full="Senior Backend Engineer at Acme Ltd. Python + AWS.",
        specificity_signals=["named_hiring_manager"],
        vagueness_signals=[],
    )


def _synthetic_ghost() -> GhostJobAssessment:
    return GhostJobAssessment(
        probability="LIKELY_REAL",
        signals=[],
        confidence="HIGH",
        raw_jd_score=GhostJobJDScore(
            named_hiring_manager=1.0,
            specific_duty_bullets=1.0,
            specific_tech_stack=1.0,
            specific_team_context=1.0,
            specific_success_metrics=1.0,
            specificity_score=5.0,
            specificity_signals=["named_hiring_manager"],
            vagueness_signals=[],
        ),
        age_days=7,
    )


def _synthetic_verdict() -> Verdict:
    return Verdict(
        decision="GO",
        confidence_pct=78,
        headline="Strong fit — apply.",
        reasoning=[],
        hard_blockers=[],
        stretch_concerns=[],
        motivation_fit=MotivationFitReport(
            motivation_evaluations=[],
            deal_breaker_evaluations=[],
            good_role_signal_evaluations=[],
        ),
    )


# ---------------------------------------------------------------------------
# Test client with storage + user seeded
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    from trajectory.config import settings
    from trajectory import storage as storage_module

    monkeypatch.setattr(settings, "sqlite_db_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "faiss_index_path", tmp_path / "test.faiss")
    monkeypatch.setattr(settings, "generated_dir", tmp_path / "generated")
    monkeypatch.setattr(settings, "demo_user_id", "demo-user-1")
    monkeypatch.setattr(storage_module, "_initialised", False)

    from trajectory.api.app import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def _seed(coro):
    return asyncio.run(coro)


def _read_sse_events(body_text: str) -> list[dict]:
    events: list[dict] = []
    for line in body_text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload:
            continue
        events.append(json.loads(payload))
    return events


@pytest.fixture
def mock_phase1(monkeypatch):
    """Mock every Phase 1 sub-agent at its module level.

    Returns the expected set of agent names that should emit
    agent_complete. Sponsor / SOC don't run for uk_resident users
    (orchestrator's run_sponsor + run_soc short-circuit), but they
    still emit an agent_complete via `await mark(...)` in the
    short-circuit branch.
    """
    from trajectory.sub_agents import (
        company_scraper,
        companies_house,
        ghost_job_detector,
        red_flags,
        reviews,
        salary_data,
        sponsor_register,
        soc_check,
        verdict,
    )

    async def fake_scraper_run(job_url, session_id=None):
        return _synthetic_company_research(), _synthetic_jd()

    async def fake_ch_lookup(company_name):
        # None = "company not found" — orchestrator still emits mark
        # on the caller side.
        return None

    async def fake_reviews_fetch(company_name):
        return []

    async def fake_salary_fetch(role, location, soc_code, posted_band=None):
        return SalarySignals(sources_consulted=["ASHE"], data_citations=[])

    async def fake_sponsor_lookup(company_name):
        return None  # uk_resident path skips; kept for completeness

    async def fake_soc_verify(jd, user):
        return None  # uk_resident path skips

    async def fake_ghost_score(
        jd, company_research, companies_house, job_url, session_id=None,
    ):
        return _synthetic_ghost()

    async def fake_red_flags_detect(
        company_research, companies_house, reviews, session_id=None,
    ):
        return RedFlagsReport(flags=[], checked=True)

    async def fake_verdict_generate(
        research_bundle, user, retrieved_entries, session_id=None,
    ):
        return _synthetic_verdict()

    monkeypatch.setattr(company_scraper, "run", fake_scraper_run)
    monkeypatch.setattr(companies_house, "lookup", fake_ch_lookup)
    monkeypatch.setattr(reviews, "fetch", fake_reviews_fetch)
    monkeypatch.setattr(salary_data, "fetch", fake_salary_fetch)
    monkeypatch.setattr(sponsor_register, "lookup", fake_sponsor_lookup)
    monkeypatch.setattr(soc_check, "verify", fake_soc_verify)
    monkeypatch.setattr(ghost_job_detector, "score", fake_ghost_score)
    monkeypatch.setattr(red_flags, "detect", fake_red_flags_detect)
    monkeypatch.setattr(verdict, "generate", fake_verdict_generate)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_end_to_end_forward_job_streams_all_phase1_events_plus_verdict(
    client, mock_phase1,
):
    """The demo money-shot: POST /api/sessions/forward_job with the
    real orchestrator, only external agents mocked. Every PHASE_1_AGENTS
    entry must emit agent_complete, verdict must follow, `done` last."""
    from trajectory.orchestrator import PHASE_1_AGENTS
    from trajectory.storage import upsert_user_profile

    _seed(upsert_user_profile(_demo_user()))

    with client.stream(
        "POST",
        "/api/sessions/forward_job",
        json={"job_url": "https://example.com/jobs/backend"},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = resp.read().decode("utf-8")

    events = _read_sse_events(body)
    types = [e.get("type") for e in events]

    # All PHASE_1_AGENTS emit a complete event (each closure calls mark()
    # in both the success branch and the short-circuit / fallback branches).
    agent_completes = {
        e["agent"] for e in events if e.get("type") == "agent_complete"
    }
    assert agent_completes == set(PHASE_1_AGENTS), (
        f"missing marks: {set(PHASE_1_AGENTS) - agent_completes}, "
        f"extras: {agent_completes - set(PHASE_1_AGENTS)}"
    )

    # Verdict is emitted after all agent_completes.
    verdict_index = types.index("verdict")
    assert all(
        types[i] == "agent_complete"
        for i in range(verdict_index)
    ), f"non-agent_complete event before verdict: {types[:verdict_index]}"

    verdict_event = events[verdict_index]
    assert verdict_event["data"]["decision"] == "GO"
    assert verdict_event["data"]["confidence_pct"] == 78

    # `done` sentinel is the last frame.
    assert types[-1] == "done"


def test_end_to_end_persists_session_with_bundle_and_verdict(
    client, mock_phase1,
):
    """After the stream closes, the session exists in storage with a
    research bundle + verdict so GET /api/sessions/{id} returns
    something useful."""
    from trajectory.storage import (
        get_recent_sessions,
        upsert_user_profile,
    )

    _seed(upsert_user_profile(_demo_user()))

    with client.stream(
        "POST",
        "/api/sessions/forward_job",
        json={"job_url": "https://example.com/jobs/backend"},
    ) as resp:
        resp.read()

    sessions = _seed(get_recent_sessions("demo-user-1", n=5))
    assert len(sessions) == 1
    s = sessions[0]
    assert s.job_url == "https://example.com/jobs/backend"
    assert s.intent == "forward_job"
    # phase1_output lands as a dict (Session stores it serialised).
    assert isinstance(s.phase1_output, dict)
    assert s.phase1_output["extracted_jd"]["role_title"] == "Senior Backend Engineer"
    assert s.phase1_output["company_research"]["company_name"] == "Acme Ltd"
    # Verdict survived the round trip too.
    assert s.verdict is not None
    assert s.verdict.decision == "GO"

    # Detail endpoint returns the full payload.
    resp = client.get(f"/api/sessions/{s.session_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"]["decision"] == "GO"
    assert (
        body["research_bundle"]["extracted_jd"]["role_title"]
        == "Senior Backend Engineer"
    )


def test_end_to_end_session_appears_in_list_after_stream(client, mock_phase1):
    """Cross-surface invariant: once the forward_job SSE completes, the
    new session is immediately visible via GET /api/sessions. This is
    the plumbing the dashboard's SessionList relies on after a stream
    closes."""
    from trajectory.storage import upsert_user_profile

    _seed(upsert_user_profile(_demo_user()))

    before = client.get("/api/sessions").json()
    assert before["sessions"] == []

    with client.stream(
        "POST",
        "/api/sessions/forward_job",
        json={"job_url": "https://example.com/jobs/x"},
    ) as resp:
        resp.read()

    after = client.get("/api/sessions").json()
    assert len(after["sessions"]) == 1
    summary = after["sessions"][0]
    assert summary["verdict"] == "GO"
    assert summary["role_title"] == "Senior Backend Engineer"
    assert summary["company_name"] == "Acme Ltd"
