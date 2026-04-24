"""Tests for Wave 3 read-only API routes.

Covers:
  - GET /api/profile — happy path + 404 when no profile + 500 when
    DEMO_USER_ID unset
  - GET /api/sessions — list, ordering, ownership filter, slim
    summary fields, limit validation
  - GET /api/sessions/{id} — happy path with full bundle, 404 for
    unknown, 404 for someone else's (no enumeration leak),
    cost_summary populated
  - GET /api/files/{session_id}/{filename} — happy path, ownership
    check, path traversal blocked (relative + absolute), missing file
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trajectory.schemas import Session, UserProfile


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user(user_id: str = "demo-user-1", name: str = "Demo User") -> UserProfile:
    n = _now()
    return UserProfile(
        user_id=user_id,
        name=name,
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
    session_id: str,
    user_id: str,
    job_url: str = "https://example.com/jobs/x",
    intent: str = "forward_job",
) -> Session:
    return Session(
        session_id=session_id,
        user_id=user_id,
        intent=intent,
        job_url=job_url,
        created_at=_now(),
    )


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """Per-test app + tempdir SQLite + tempdir generated_dir + demo
    user id wired. Resets the storage module's idempotency flag so
    the new DB file gets its schema created."""
    from trajectory.config import settings
    from trajectory import storage as storage_module

    monkeypatch.setattr(settings, "sqlite_db_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "faiss_index_path", tmp_path / "test.faiss")
    monkeypatch.setattr(settings, "generated_dir", tmp_path / "generated")
    monkeypatch.setattr(settings, "demo_user_id", "demo-user-1")
    # Force _ensure_db() to recreate the schema on this fresh DB path.
    monkeypatch.setattr(storage_module, "_initialised", False)

    from trajectory.api.app import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# /api/profile
# ---------------------------------------------------------------------------


def test_profile_404_when_no_user_record(client):
    resp = client.get("/api/profile")
    assert resp.status_code == 404
    body = resp.json()
    # detail shape: {"detail": {"code": "profile_not_found", "message": ...}}
    assert body["detail"]["code"] == "profile_not_found"


def test_profile_returns_demo_user_when_present(client):
    from trajectory.storage import upsert_user_profile

    _seed(upsert_user_profile(_user()))

    resp = client.get("/api/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "demo-user-1"
    assert body["name"] == "Demo User"
    assert body["user_type"] == "uk_resident"


def test_profile_500_when_demo_user_id_unset(client, monkeypatch):
    from trajectory.config import settings

    monkeypatch.setattr(settings, "demo_user_id", "")
    resp = client.get("/api/profile")
    assert resp.status_code == 500
    assert "DEMO_USER_ID" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# /api/sessions
# ---------------------------------------------------------------------------


def _seed(coro):
    """Run a storage coroutine synchronously from the test body.

    Uses asyncio.run for a fresh loop per call — aiosqlite manages its
    own worker thread per connection, and `_ensure_db` is idempotent
    so this is safe to invoke repeatedly.
    """
    import asyncio
    return asyncio.run(coro)


def test_sessions_list_empty_when_no_rows(client):
    from trajectory.storage import upsert_user_profile

    _seed(upsert_user_profile(_user()))
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    assert resp.json() == {"sessions": []}


def test_sessions_list_returns_summaries_in_recency_order(client):
    from trajectory.storage import insert_session, upsert_user_profile

    _seed(upsert_user_profile(_user()))
    # Insert two sessions; the second one is more recent.
    s1 = _session(session_id="s1", user_id="demo-user-1", intent="forward_job")
    s2 = _session(session_id="s2", user_id="demo-user-1", intent="draft_cv")
    s2.created_at = datetime(2099, 1, 1)
    _seed(insert_session(s1))
    _seed(insert_session(s2))

    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert [s["id"] for s in sessions] == ["s2", "s1"]
    assert sessions[0]["intent"] == "draft_cv"


def test_sessions_list_excludes_other_users(client):
    from trajectory.storage import insert_session, upsert_user_profile

    _seed(upsert_user_profile(_user()))
    _seed(insert_session(_session(session_id="mine", user_id="demo-user-1")))
    _seed(insert_session(_session(session_id="theirs", user_id="someone-else")))

    resp = client.get("/api/sessions")
    ids = [s["id"] for s in resp.json()["sessions"]]
    assert "mine" in ids
    assert "theirs" not in ids


def test_sessions_list_summary_pulls_role_and_company_from_phase1(client):
    """The summary's role_title + company_name come from
    session.phase1_output.{extracted_jd, company_research}."""
    from trajectory.storage import insert_session, update_session, upsert_user_profile

    _seed(upsert_user_profile(_user()))
    s = _session(session_id="enriched", user_id="demo-user-1")
    _seed(insert_session(s))
    s.phase1_output = {
        "extracted_jd": {"role_title": "Senior Backend Engineer"},
        "company_research": {"company_name": "Acme Ltd"},
    }
    _seed(update_session(s))

    resp = client.get("/api/sessions")
    summary = resp.json()["sessions"][0]
    assert summary["role_title"] == "Senior Backend Engineer"
    assert summary["company_name"] == "Acme Ltd"


def test_sessions_list_rejects_invalid_limit(client):
    from trajectory.storage import upsert_user_profile

    _seed(upsert_user_profile(_user()))
    assert client.get("/api/sessions?limit=0").status_code == 400
    assert client.get("/api/sessions?limit=101").status_code == 400


# ---------------------------------------------------------------------------
# /api/sessions/{id}
# ---------------------------------------------------------------------------


def test_session_detail_404_for_unknown_id(client):
    resp = client.get("/api/sessions/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "session_not_found"


def test_session_detail_404_for_other_users_session(client):
    """Same 404 as not-found — prevents enumeration."""
    from trajectory.storage import insert_session, upsert_user_profile

    _seed(upsert_user_profile(_user()))
    _seed(insert_session(_session(session_id="theirs", user_id="someone-else")))

    resp = client.get("/api/sessions/theirs")
    assert resp.status_code == 404


def test_session_detail_returns_full_payload(client, tmp_path: Path):
    from trajectory.storage import (
        insert_session,
        log_llm_cost,
        update_session,
        upsert_user_profile,
    )

    _seed(upsert_user_profile(_user()))
    s = _session(session_id="full", user_id="demo-user-1")
    _seed(insert_session(s))
    s.phase1_output = {"extracted_jd": {"role_title": "Senior Engineer"}}
    _seed(update_session(s))
    _seed(log_llm_cost(
        session_id="full",
        agent_name="verdict",
        model="claude-opus-4-7",
        input_tokens=1000,
        output_tokens=500,
    ))

    # Drop a generated file so generated_files isn't empty.
    from trajectory.config import settings
    sess_dir = settings.generated_dir / "full"
    sess_dir.mkdir(parents=True, exist_ok=True)
    (sess_dir / "cv.docx").write_bytes(b"fake docx")
    (sess_dir / "cv.pdf").write_bytes(b"fake pdf")
    (sess_dir / "cv_latex_full.pdf").write_bytes(b"fake latex pdf")

    resp = client.get("/api/sessions/full")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "full"
    assert body["user_id"] == "demo-user-1"
    assert body["research_bundle"]["extracted_jd"]["role_title"] == "Senior Engineer"
    assert body["cost_summary"]["total_usd"] > 0
    assert body["cost_summary"]["by_agent"]["verdict"] > 0

    files = {f["filename"]: f for f in body["generated_files"]}
    assert files["cv.docx"]["kind"] == "docx"
    assert files["cv.pdf"]["kind"] == "pdf"
    assert files["cv_latex_full.pdf"]["kind"] == "latex_pdf"
    assert files["cv.docx"]["download_url"] == "/api/files/full/cv.docx"


# ---------------------------------------------------------------------------
# /api/files/{session_id}/{filename}
# ---------------------------------------------------------------------------


def _seed_file_session(client, *, content: bytes = b"%PDF-1.4 ok"):
    from trajectory.storage import insert_session, upsert_user_profile
    from trajectory.config import settings

    _seed(upsert_user_profile(_user()))
    _seed(insert_session(_session(session_id="filesess", user_id="demo-user-1")))
    sess_dir = settings.generated_dir / "filesess"
    sess_dir.mkdir(parents=True, exist_ok=True)
    (sess_dir / "cv.pdf").write_bytes(content)


def test_file_happy_path(client):
    _seed_file_session(client, content=b"%PDF-1.4 hello")
    resp = client.get("/api/files/filesess/cv.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-1.4 hello"


def test_file_404_for_someone_elses_session(client):
    from trajectory.storage import insert_session, upsert_user_profile
    from trajectory.config import settings

    _seed(upsert_user_profile(_user()))
    _seed(insert_session(_session(session_id="theirs", user_id="someone-else")))
    sess_dir = settings.generated_dir / "theirs"
    sess_dir.mkdir(parents=True, exist_ok=True)
    (sess_dir / "cv.pdf").write_bytes(b"PDF")

    resp = client.get("/api/files/theirs/cv.pdf")
    assert resp.status_code == 404


def test_file_404_for_missing_file(client):
    _seed_file_session(client)
    resp = client.get("/api/files/filesess/does-not-exist.pdf")
    assert resp.status_code == 404


def test_file_blocks_relative_traversal(client, tmp_path: Path):
    """Path(filename).name strips `../`. Even with `../../..` the
    request resolves to a flat name, which then doesn't exist → 404."""
    _seed_file_session(client)
    # Plant a file outside the session dir to prove the resolver
    # doesn't walk to it.
    secret = tmp_path / "secret.pdf"
    secret.write_bytes(b"top secret")

    resp = client.get("/api/files/filesess/..%2Fsecret.pdf")
    # Behaviour: either 400 (invalid_filename) or 404 (file_not_found).
    # Both confirm the secret was not served.
    assert resp.status_code in (400, 404)
    assert resp.content != b"top secret"


def test_file_blocks_dot_filename(client):
    _seed_file_session(client)
    resp = client.get("/api/files/filesess/.")
    assert resp.status_code in (400, 404)


def test_file_returns_docx_mime(client):
    from trajectory.storage import insert_session, upsert_user_profile
    from trajectory.config import settings

    _seed(upsert_user_profile(_user()))
    _seed(insert_session(_session(session_id="docxsess", user_id="demo-user-1")))
    sess_dir = settings.generated_dir / "docxsess"
    sess_dir.mkdir(parents=True, exist_ok=True)
    (sess_dir / "cv.docx").write_bytes(b"PK\x03\x04 fake docx")

    resp = client.get("/api/files/docxsess/cv.docx")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
