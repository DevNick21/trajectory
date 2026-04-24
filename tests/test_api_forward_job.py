"""Tests for POST /api/sessions/forward_job (Wave 4 SSE).

handle_forward_job is fully mocked — no real LLM, no scrape. The mock
emits a few `agent_complete` events through the supplied emitter and
returns a synthetic verdict. Tests assert:

  - Auth gate: 404 when no profile, 422 when body missing
  - Happy path: stream contains agent_complete events + verdict + done
  - Error path: handle_forward_job raises → stream contains error + done
  - Verdict event: shape matches Verdict.model_dump(mode="json")
  - Session is persisted before Phase 1 starts
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trajectory.schemas import (
    GhostJobAssessment,
    GhostJobJDScore,
    MotivationFitReport,
    RedFlagsReport,
    ResearchBundle,
    SalarySignals,
    UserProfile,
    Verdict,
    CompanyResearch,
    ExtractedJobDescription,
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user(user_id: str = "demo-user-1") -> UserProfile:
    n = _now()
    return UserProfile(
        user_id=user_id,
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


def _make_verdict() -> Verdict:
    return Verdict(
        decision="GO",
        confidence_pct=80,
        headline="Strong fit; proceed.",
        reasoning=[],
        hard_blockers=[],
        stretch_concerns=[],
        motivation_fit=MotivationFitReport(
            motivation_evaluations=[],
            deal_breaker_evaluations=[],
            good_role_signal_evaluations=[],
        ),
    )


def _make_bundle(session_id: str) -> ResearchBundle:
    n = _now()
    return ResearchBundle(
        session_id=session_id,
        extracted_jd=ExtractedJobDescription(
            role_title="Senior Backend Engineer",
            seniority_signal="senior",
            soc_code_guess="2136",
            soc_code_reasoning="Software role.",
            location="London",
            remote_policy="hybrid",
            required_skills=["Python"],
            posting_platform="company_site",
            hiring_manager_named=False,
            jd_text_full="JD body",
            specificity_signals=[],
            vagueness_signals=[],
        ),
        company_research=CompanyResearch(company_name="Acme", scraped_pages=[]),
        ghost_job=GhostJobAssessment(
            probability="LIKELY_REAL",
            signals=[],
            confidence="HIGH",
            raw_jd_score=GhostJobJDScore(
                named_hiring_manager=1, specific_duty_bullets=1,
                specific_tech_stack=1, specific_team_context=1,
                specific_success_metrics=1, specificity_score=5,
                specificity_signals=[], vagueness_signals=[],
            ),
        ),
        salary_signals=SalarySignals(sources_consulted=[], data_citations=[]),
        red_flags=RedFlagsReport(flags=[], checked=True),
        bundle_completed_at=n,
    )


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
    import asyncio
    return asyncio.run(coro)


def _read_sse_events(response) -> list[dict]:
    """Decode an SSE response body into a list of parsed JSON events."""
    events: list[dict] = []
    for raw in response.text.splitlines():
        if not raw.startswith("data:"):
            continue
        payload = raw[len("data:"):].strip()
        if not payload:
            continue
        events.append(json.loads(payload))
    return events


# ---------------------------------------------------------------------------
# Auth + validation
# ---------------------------------------------------------------------------


def test_forward_job_404_when_no_profile(client):
    """Without a profile, the demo user can't start a job — frontend
    should redirect to onboarding instead."""
    resp = client.post(
        "/api/sessions/forward_job",
        json={"job_url": "https://example.com/jobs/x"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "profile_not_found"


def test_forward_job_422_when_body_missing(client):
    from trajectory.storage import upsert_user_profile

    _seed(upsert_user_profile(_user()))
    resp = client.post("/api/sessions/forward_job", json={})
    assert resp.status_code == 422


def test_forward_job_422_for_non_url(client):
    from trajectory.storage import upsert_user_profile

    _seed(upsert_user_profile(_user()))
    resp = client.post("/api/sessions/forward_job", json={"job_url": "not a url"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_handle_forward_job(monkeypatch):
    """Patch the orchestrator entry point to emit a few events and
    return a synthetic bundle + verdict — no real Phase 1.

    Returns a list that captures call kwargs for assertions.
    """
    calls: list[dict] = []

    async def fake(**kwargs):
        emitter = kwargs["emitter"]
        session = kwargs["session"]
        # Simulate a handful of agent completions through the emitter.
        await emitter.emit({"type": "agent_complete", "agent": "phase_1_jd_extractor"})
        await emitter.emit({"type": "agent_complete", "agent": "phase_1_company_scraper_summariser"})
        await emitter.emit({"type": "agent_complete", "agent": "companies_house"})
        await emitter.emit({"type": "agent_complete", "agent": "soc_check"})
        calls.append(kwargs)
        return _make_bundle(session.session_id), _make_verdict()

    # Patch where it's looked up — sessions.py does a lazy import.
    import trajectory.orchestrator as orch_module
    monkeypatch.setattr(orch_module, "handle_forward_job", fake)
    return calls


def test_forward_job_streams_progress_then_verdict_then_done(
    client, mock_handle_forward_job,
):
    from trajectory.storage import upsert_user_profile

    _seed(upsert_user_profile(_user()))

    with client.stream(
        "POST",
        "/api/sessions/forward_job",
        json={"job_url": "https://example.com/jobs/x"},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = resp.read().decode("utf-8")

    # Reconstruct a Response-like object for the helper.
    class _R:
        text = body
    events = _read_sse_events(_R())

    types = [e.get("type") for e in events]
    # All four agent_completes precede the verdict, which precedes done.
    assert types[:4] == [
        "agent_complete", "agent_complete", "agent_complete", "agent_complete",
    ]
    assert "verdict" in types
    assert types[-1] == "done"

    # Verdict event carries the Verdict.model_dump(mode='json') payload.
    verdict_event = next(e for e in events if e["type"] == "verdict")
    assert verdict_event["data"]["decision"] == "GO"
    assert verdict_event["data"]["confidence_pct"] == 80


def test_forward_job_persists_session_before_orchestrator_runs(
    client, mock_handle_forward_job,
):
    """The session must be in the DB by the time the orchestrator
    starts (so it can save phase1_output / verdict against it)."""
    from trajectory.storage import upsert_user_profile, get_recent_sessions

    _seed(upsert_user_profile(_user()))

    with client.stream(
        "POST",
        "/api/sessions/forward_job",
        json={"job_url": "https://example.com/jobs/y"},
    ) as resp:
        resp.read()

    sessions = _seed(get_recent_sessions("demo-user-1", n=10))
    assert len(sessions) == 1
    assert sessions[0].job_url == "https://example.com/jobs/y"
    assert sessions[0].intent == "forward_job"


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------


def test_forward_job_emits_error_event_when_orchestrator_raises(
    client, monkeypatch,
):
    from trajectory.storage import upsert_user_profile

    _seed(upsert_user_profile(_user()))

    async def fake(**kwargs):
        raise RuntimeError("simulated scrape failure")

    import trajectory.orchestrator as orch_module
    monkeypatch.setattr(orch_module, "handle_forward_job", fake)

    with client.stream(
        "POST",
        "/api/sessions/forward_job",
        json={"job_url": "https://example.com/jobs/z"},
    ) as resp:
        assert resp.status_code == 200
        body = resp.read().decode("utf-8")

    class _R:
        text = body
    events = _read_sse_events(_R())
    types = [e.get("type") for e in events]

    assert "error" in types
    error_event = next(e for e in events if e["type"] == "error")
    # Don't leak raw exception strings to the client.
    assert "simulated scrape failure" not in error_event["data"]["message"]
    # `error` is itself terminal — the SSE iterator breaks on it,
    # so the trailing `done` sentinel is never delivered. The
    # frontend treats either as the end-of-stream signal.
    assert types[-1] == "error"
