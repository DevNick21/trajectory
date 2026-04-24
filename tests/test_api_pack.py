"""Tests for the Wave 5 pack endpoints.

Each orchestrator handler is fully mocked — no real LLM, no real
renderer. Tests cover:

  - Individual endpoints: 404 ownership, 409 precondition, happy path
    JSON shape (output + generated_files), file scan integration
  - full_prep SSE: 409 when no bundle, started+completed events for
    each generator, partial failure (one fails, three succeed),
    `done` sentinel last
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from trajectory.schemas import (
    CoverLetterOutput,
    CVBullet,
    CVOutput,
    CVRole,
    LikelyQuestion,
    LikelyQuestionsOutput,
    ReasoningPoint,
    SalaryRecommendation,
    Session,
    UserProfile,
    Citation,
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


def _session(
    *,
    session_id: str = "sess1",
    user_id: str = "demo-user-1",
    with_bundle: bool = True,
) -> Session:
    s = Session(
        session_id=session_id,
        user_id=user_id,
        intent="forward_job",
        job_url="https://example.com/jobs/x",
        created_at=_now(),
    )
    if with_bundle:
        s.phase1_output = {
            "extracted_jd": {"role_title": "Senior Engineer"},
            "company_research": {"company_name": "Acme"},
        }
    return s


def _cv() -> CVOutput:
    return CVOutput(
        name="Demo",
        contact={"email": "x@y.com"},
        professional_summary="Summary.",
        experience=[
            CVRole(
                title="Engineer",
                company="Acme",
                dates="2024-2026",
                bullets=[
                    CVBullet(
                        text="[ce:e1] Did the thing.",
                        citations=[Citation(kind="career_entry", entry_id="e1")],
                    )
                ],
            )
        ],
        education=[],
        skills=["Python"],
    )


def _cl() -> CoverLetterOutput:
    return CoverLetterOutput(
        addressed_to="Hiring Manager",
        paragraphs=["Para 1.", "Para 2."],
        citations=[],
        word_count=100,
    )


def _lq() -> LikelyQuestionsOutput:
    return LikelyQuestionsOutput(
        questions=[
            LikelyQuestion(
                question="Tell me about a project.",
                bucket="experience",
                likelihood="HIGH",
                why_likely="Common opener.",
                citation=Citation(kind="career_entry", entry_id="e1"),
                strategy_note="Use STAR.",
                relevant_career_entry_ids=["e1"],
            )
        ]
    )


def _sal() -> SalaryRecommendation:
    return SalaryRecommendation(
        opening_number=80_000,
        opening_phrasing="I'm looking for £80k.",
        floor=70_000,
        ceiling=95_000,
        reasoning=[
            ReasoningPoint(
                claim="Market rate for SOC 2136 in London.",
                supporting_evidence="ASHE p50 2024.",
                citation=Citation(
                    kind="gov_data",
                    data_field="ashe.soc2136.london.p50",
                    data_value="78000",
                ),
            )
        ],
        sponsor_constraint_active=False,
        confidence="HIGH",
        scripts={"opening": "...", "counter_low": "..."},
        data_gaps=[],
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


def _drop_session(session: Session, *, with_pack_files: bool = False):
    """Insert a session and (optionally) seed renderer outputs.

    Always seeds the demo user's profile so get_current_user returns
    200 — the auth gate is checked first; the session ownership
    check is what we want to exercise next.
    """
    from trajectory.config import settings
    from trajectory.storage import insert_session, upsert_user_profile

    _seed(upsert_user_profile(_user("demo-user-1")))
    if session.user_id != "demo-user-1":
        _seed(upsert_user_profile(_user(session.user_id)))
    _seed(insert_session(session))
    if with_pack_files:
        sd = settings.generated_dir / session.session_id
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "cv.docx").write_bytes(b"PK fake docx")
        (sd / "cv.pdf").write_bytes(b"%PDF fake")


def _patch_handlers(monkeypatch, **overrides: Any) -> None:
    """Patch the orchestrator handlers used by api/routes/pack.py.

    `overrides` lets a test substitute a particular handler with a
    custom mock (e.g. one that raises). Defaults are happy-path
    returns matching the real signatures.
    """
    import trajectory.orchestrator as orch

    async def fake_cv(session, user, storage, *args, **kwargs):
        return _cv(), Path("/tmp/cv.docx"), Path("/tmp/cv.pdf"), None

    async def fake_cl(session, user, storage, *args, **kwargs):
        return _cl(), Path("/tmp/cl.docx"), Path("/tmp/cl.pdf")

    async def fake_lq(session, user, storage, *args, **kwargs):
        return _lq()

    async def fake_sal(session, user, storage, *args, **kwargs):
        return _sal()

    monkeypatch.setattr(orch, "handle_draft_cv", overrides.get("cv", fake_cv))
    monkeypatch.setattr(orch, "handle_draft_cover_letter", overrides.get("cover_letter", fake_cl))
    monkeypatch.setattr(orch, "handle_predict_questions", overrides.get("questions", fake_lq))
    monkeypatch.setattr(orch, "handle_salary_advice", overrides.get("salary", fake_sal))


def _read_sse_events(body_text: str) -> list[dict]:
    out: list[dict] = []
    for line in body_text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload:
            continue
        out.append(json.loads(payload))
    return out


# ---------------------------------------------------------------------------
# Individual endpoints — auth + ownership + precondition
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("endpoint", ["cv", "cover_letter", "questions", "salary"])
def test_individual_endpoint_404_without_profile(client, endpoint):
    resp = client.post(f"/api/sessions/sess1/{endpoint}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "profile_not_found"


@pytest.mark.parametrize("endpoint", ["cv", "cover_letter", "questions", "salary"])
def test_individual_endpoint_404_for_someone_elses_session(
    client, monkeypatch, endpoint,
):
    _patch_handlers(monkeypatch)
    _drop_session(_session(session_id="theirs", user_id="someone-else"))
    resp = client.post(f"/api/sessions/theirs/{endpoint}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "session_not_found"


@pytest.mark.parametrize("endpoint", ["cv", "cover_letter", "questions", "salary"])
def test_individual_endpoint_409_when_handler_raises_value_error(
    client, monkeypatch, endpoint,
):
    """Domain precondition (e.g. no research bundle on session) →
    handler raises ValueError → endpoint returns 409 with code."""
    async def boom(*args, **kwargs):
        raise ValueError("no research bundle on session — forward a job first")

    _patch_handlers(monkeypatch, **{endpoint: boom})
    _drop_session(_session(with_bundle=False))

    resp = client.post(f"/api/sessions/sess1/{endpoint}")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "precondition_failed"


# ---------------------------------------------------------------------------
# Individual endpoints — happy path
# ---------------------------------------------------------------------------


def test_cv_endpoint_returns_pack_result_with_files(client, monkeypatch):
    _patch_handlers(monkeypatch)
    _drop_session(_session(), with_pack_files=True)

    resp = client.post("/api/sessions/sess1/cv")
    assert resp.status_code == 200
    body = resp.json()
    assert body["generator"] == "cv"
    assert body["output"]["name"] == "Demo"
    assert body["output"]["experience"][0]["bullets"][0]["text"].startswith("[ce:e1]")

    files = {f["filename"]: f for f in body["generated_files"]}
    assert "cv.docx" in files
    assert files["cv.docx"]["download_url"] == "/api/files/sess1/cv.docx"


def test_cover_letter_endpoint_happy_path(client, monkeypatch):
    _patch_handlers(monkeypatch)
    _drop_session(_session())
    resp = client.post("/api/sessions/sess1/cover_letter")
    assert resp.status_code == 200
    assert resp.json()["output"]["addressed_to"] == "Hiring Manager"


def test_questions_endpoint_happy_path(client, monkeypatch):
    _patch_handlers(monkeypatch)
    _drop_session(_session())
    resp = client.post("/api/sessions/sess1/questions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["generator"] == "questions"
    assert len(body["output"]["questions"]) == 1


def test_salary_endpoint_happy_path(client, monkeypatch):
    _patch_handlers(monkeypatch)
    _drop_session(_session())
    resp = client.post("/api/sessions/sess1/salary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["output"]["opening_number"] == 80_000


# ---------------------------------------------------------------------------
# full_prep SSE
# ---------------------------------------------------------------------------


def test_full_prep_409_when_no_bundle(client, monkeypatch):
    _patch_handlers(monkeypatch)
    _drop_session(_session(with_bundle=False))
    resp = client.post("/api/sessions/sess1/full_prep")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "precondition_failed"


def test_full_prep_streams_started_completed_done(client, monkeypatch):
    _patch_handlers(monkeypatch)
    _drop_session(_session(), with_pack_files=True)

    with client.stream(
        "POST", "/api/sessions/sess1/full_prep",
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = resp.read().decode("utf-8")

    events = _read_sse_events(body)
    types = [e["type"] for e in events]

    # All four generators emit started + completed.
    started = [e for e in events if e["type"] == "started"]
    completed = [e for e in events if e["type"] == "completed"]
    assert {e["generator"] for e in started} == {"cv", "cover_letter", "questions", "salary"}
    assert {e["generator"] for e in completed} == {"cv", "cover_letter", "questions", "salary"}

    # done sentinel last.
    assert types[-1] == "done"

    # CV completed event carries generated_files (the file scan saw
    # cv.docx + cv.pdf seeded above).
    cv_completed = next(e for e in completed if e["generator"] == "cv")
    file_names = {f["filename"] for f in cv_completed["generated_files"]}
    assert "cv.docx" in file_names


def test_full_prep_partial_failure_emits_failed_event(client, monkeypatch):
    """One generator raises; the others still stream completed events
    (return_exceptions=True style — the SSE consumer can render
    partial success)."""
    async def boom(*args, **kwargs):
        raise RuntimeError("salary_strategist exploded")

    _patch_handlers(monkeypatch, salary=boom)
    _drop_session(_session())

    with client.stream(
        "POST", "/api/sessions/sess1/full_prep",
    ) as resp:
        body = resp.read().decode("utf-8")

    events = _read_sse_events(body)
    completed_names = {e["generator"] for e in events if e["type"] == "completed"}
    failed = [e for e in events if e["type"] == "failed"]

    assert completed_names == {"cv", "cover_letter", "questions"}
    assert len(failed) == 1
    assert failed[0]["generator"] == "salary"
    # Sanitised — raw exception NOT leaked.
    assert "salary_strategist exploded" not in failed[0]["error"]
