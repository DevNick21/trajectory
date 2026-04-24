"""Tests for the batch queue API (#5).

Covers the four endpoints:
  - POST /api/queue           (single + multi URL add, dedupe, 400/422)
  - GET /api/queue            (list + status counters, ownership filter)
  - DELETE /api/queue/{id}    (happy + 404 ownership)
  - POST /api/queue/process   (SSE batch with mocked handle_forward_job)
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
    ResearchBundle,
    SalarySignals,
    UserProfile,
    Verdict,
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


def _seed_profile():
    from trajectory.storage import upsert_user_profile
    _seed(upsert_user_profile(_user()))


def _read_sse_events(body_text: str) -> list[dict]:
    out: list[dict] = []
    for line in body_text.splitlines():
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                out.append(json.loads(payload))
    return out


# ---------------------------------------------------------------------------
# POST /api/queue
# ---------------------------------------------------------------------------


def test_add_single_url(client):
    _seed_profile()
    resp = client.post(
        "/api/queue",
        json={"job_url": "https://example.com/jobs/one"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body) == 1
    assert body[0]["job_url"] == "https://example.com/jobs/one"
    assert body[0]["status"] == "pending"


def test_add_multi_urls_dedupes(client):
    _seed_profile()
    resp = client.post(
        "/api/queue",
        json={
            "job_urls": [
                "https://example.com/a",
                "https://example.com/b",
                "https://example.com/a",  # duplicate — one insert
            ],
        },
    )
    assert resp.status_code == 201
    urls = [it["job_url"] for it in resp.json()]
    assert urls == ["https://example.com/a", "https://example.com/b"]


def test_add_empty_payload_rejected(client):
    _seed_profile()
    resp = client.post("/api/queue", json={})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "empty_payload"


def test_add_invalid_url_is_422(client):
    _seed_profile()
    resp = client.post("/api/queue", json={"job_url": "not a url"})
    assert resp.status_code == 422


def test_add_404_without_profile(client):
    resp = client.post("/api/queue", json={"job_url": "https://example.com/x"})
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "profile_not_found"


# ---------------------------------------------------------------------------
# GET /api/queue
# ---------------------------------------------------------------------------


def test_list_empty_queue(client):
    _seed_profile()
    resp = client.get("/api/queue")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["pending_count"] == 0
    assert body["done_count"] == 0


def test_list_returns_counters_and_recency_order(client):
    _seed_profile()
    from trajectory.storage import insert_queued_job, mark_queued_job_done

    # Inserts are recency-ordered DESC on added_at — seed in order we
    # want to see returned (latest first).
    _seed(insert_queued_job("demo-user-1", "https://example.com/first"))
    second = _seed(insert_queued_job("demo-user-1", "https://example.com/second"))
    _seed(insert_queued_job("demo-user-1", "https://example.com/third"))
    _seed(mark_queued_job_done(second.id, "sess-xyz"))

    resp = client.get("/api/queue")
    body = resp.json()
    urls = [it["job_url"] for it in body["items"]]
    # Seeded second third in the order first, second, third — list is
    # DESC on added_at so the list order is third, second, first.
    assert urls[0].endswith("third")
    assert urls[-1].endswith("first")
    assert body["pending_count"] == 2
    assert body["done_count"] == 1


def test_list_filters_by_user(client):
    _seed_profile()
    from trajectory.storage import insert_queued_job, upsert_user_profile

    _seed(upsert_user_profile(_user("someone-else")))
    _seed(insert_queued_job("demo-user-1", "https://example.com/mine"))
    _seed(insert_queued_job("someone-else", "https://example.com/theirs"))

    body = client.get("/api/queue").json()
    urls = [it["job_url"] for it in body["items"]]
    assert "https://example.com/mine" in urls
    assert "https://example.com/theirs" not in urls


# ---------------------------------------------------------------------------
# DELETE /api/queue/{id}
# ---------------------------------------------------------------------------


def test_delete_queued_job(client):
    _seed_profile()
    add = client.post(
        "/api/queue", json={"job_url": "https://example.com/gone"}
    ).json()
    job_id = add[0]["id"]

    resp = client.delete(f"/api/queue/{job_id}")
    assert resp.status_code == 204
    assert client.get("/api/queue").json()["items"] == []


def test_delete_404_for_unknown(client):
    _seed_profile()
    resp = client.delete("/api/queue/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "queued_job_not_found"


def test_delete_404_for_someone_elses(client):
    """Same 404 shape as not-found — no enumeration."""
    _seed_profile()
    from trajectory.storage import insert_queued_job, upsert_user_profile

    _seed(upsert_user_profile(_user("someone-else")))
    job = _seed(insert_queued_job("someone-else", "https://example.com/theirs"))

    resp = client.delete(f"/api/queue/{job.id}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/queue/process — SSE batch
# ---------------------------------------------------------------------------


def _bundle() -> ResearchBundle:
    n = _now()
    return ResearchBundle(
        session_id="s1",
        extracted_jd=ExtractedJobDescription(
            role_title="Senior Engineer",
            seniority_signal="senior",
            soc_code_guess="2136",
            soc_code_reasoning="Software.",
            location="London",
            remote_policy="hybrid",
            required_skills=["Python"],
            posting_platform="company_site",
            hiring_manager_named=False,
            jd_text_full="x",
            specificity_signals=[],
            vagueness_signals=[],
        ),
        company_research=CompanyResearch(
            company_name="Acme Ltd", scraped_pages=[],
        ),
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


def _verdict(decision: str = "GO", headline: str = "Go for it.") -> Verdict:
    return Verdict(
        decision=decision,  # type: ignore[arg-type]
        confidence_pct=80,
        headline=headline,
        reasoning=[],
        hard_blockers=[],
        stretch_concerns=[],
        motivation_fit=MotivationFitReport(
            motivation_evaluations=[],
            deal_breaker_evaluations=[],
            good_role_signal_evaluations=[],
        ),
    )


def test_process_empty_queue_emits_done_with_note(client):
    _seed_profile()
    with client.stream("POST", "/api/queue/process") as resp:
        assert resp.status_code == 200
        body = resp.read().decode("utf-8")

    events = _read_sse_events(body)
    assert events[-1]["type"] == "done"
    assert events[-1]["processed_count"] == 0


def test_process_batch_streams_per_job_events(client, monkeypatch):
    _seed_profile()

    # Seed two pending jobs.
    client.post(
        "/api/queue",
        json={"job_urls": [
            "https://example.com/one",
            "https://example.com/two",
        ]},
    )

    async def fake_forward(**kwargs):
        return _bundle(), _verdict()

    import trajectory.orchestrator as orch
    monkeypatch.setattr(orch, "handle_forward_job", fake_forward)

    with client.stream("POST", "/api/queue/process") as resp:
        assert resp.status_code == 200
        body = resp.read().decode("utf-8")

    events = _read_sse_events(body)
    types = [e["type"] for e in events]
    started = [e for e in events if e["type"] == "started"]
    completed = [e for e in events if e["type"] == "completed"]

    assert len(started) == 2
    assert len(completed) == 2
    for c in completed:
        assert c["verdict_decision"] == "GO"
        assert c["role_title"] == "Senior Engineer"
        assert c["company_name"] == "Acme Ltd"
        assert c["session_id"]  # non-empty
    assert types[-1] == "done"
    assert events[-1]["processed_count"] == 2

    # All jobs now marked `done` with a session_id.
    queue = client.get("/api/queue").json()
    for it in queue["items"]:
        assert it["status"] == "done"
        assert it["session_id"] is not None


def test_process_batch_handles_partial_failure(client, monkeypatch):
    _seed_profile()

    add = client.post(
        "/api/queue",
        json={"job_urls": [
            "https://example.com/good",
            "https://example.com/bad",
        ]},
    ).json()
    bad_id = next(it["id"] for it in add if "bad" in it["job_url"])

    async def fake_forward(*, job_url, **kwargs):
        if "bad" in job_url:
            raise RuntimeError("simulated scrape failure")
        return _bundle(), _verdict()

    import trajectory.orchestrator as orch
    monkeypatch.setattr(orch, "handle_forward_job", fake_forward)

    with client.stream("POST", "/api/queue/process") as resp:
        body = resp.read().decode("utf-8")

    events = _read_sse_events(body)
    failed = [e for e in events if e["type"] == "failed"]
    completed = [e for e in events if e["type"] == "completed"]

    assert len(failed) == 1
    assert failed[0]["id"] == bad_id
    # Sanitised — raw exception NOT leaked.
    assert "simulated scrape failure" not in failed[0]["error"]
    assert len(completed) == 1
    assert events[-1]["type"] == "done"
    assert events[-1]["processed_count"] == 2

    # The bad row is marked `failed` with a populated error string.
    queue = {it["id"]: it for it in client.get("/api/queue").json()["items"]}
    assert queue[bad_id]["status"] == "failed"
    assert "simulated scrape failure" in queue[bad_id]["error"]
