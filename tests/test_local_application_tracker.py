from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_local_application_refreshes_evidence_after_cv_entry(tmp_path, monkeypatch) -> None:
    from askpicky.applications import (
        create_local_application_from_jd,
        delete_application,
        get_application,
        list_applications,
        refresh_application_evidence,
        update_application_metadata,
        update_application_status,
    )
    from askpicky.config import settings
    from askpicky.schemas import CareerEntry
    import askpicky.storage as storage_module
    from askpicky.storage import Storage

    monkeypatch.setattr(settings, "sqlite_db_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "faiss_index_path", tmp_path / "test.faiss")
    monkeypatch.setattr(storage_module, "_initialised", False)

    user_id = "local_tracker_user"
    storage = Storage()
    await storage.initialise()

    jd_text = """
    Backend Engineer

    Build Python services with FastAPI and PostgreSQL. Candidates should
    be comfortable with SQL and Docker.
    """
    application = await create_local_application_from_jd(
        user_id=user_id,
        jd_text=jd_text,
        company_name="Local Test Co",
    )

    assert application.source == "local_jd"
    assert application.evidence_snapshot is not None
    assert any(
        item.status == "needs_profile"
        for item in application.evidence_snapshot.evidence_checkpoints
        if item.requirement == "python"
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    await storage.insert_career_entry(
        CareerEntry(
            entry_id="cv-python-fastapi",
            user_id=user_id,
            kind="cv_bullet",
            raw_text="Built Python and FastAPI services with PostgreSQL in production.",
            structured={"source": "sample_cv"},
            embedding=[0.0] * 384,
            created_at=now,
        )
    )

    applications = await list_applications(user_id=user_id)
    refreshed = applications[0]

    assert refreshed.session_id == application.session_id
    assert refreshed.evidence_snapshot is not None
    assert any(
        item.status == "matched"
        for item in refreshed.evidence_snapshot.evidence_checkpoints
        if item.requirement in {"python", "fastapi", "postgres"}
    )

    updated = await update_application_status(
        session_id=application.session_id,
        new_status="applied",
        user_id=user_id,
    )
    assert updated is not None
    assert updated.status == "applied"

    edited = await update_application_metadata(
        user_id=user_id,
        session_id=application.session_id,
        company_name="Edited Company",
        role_title="Edited Backend Engineer",
        notes="High priority after CV import.",
    )
    assert edited is not None
    assert edited.company_name == "Edited Company"
    assert edited.role_title == "Edited Backend Engineer"
    assert edited.notes == "High priority after CV import."

    detail = await get_application(user_id=user_id, session_id=application.session_id)
    assert detail is not None
    assert detail.evidence_snapshot is not None

    forced = await refresh_application_evidence(
        user_id=user_id,
        session_id=application.session_id,
    )
    assert forced is not None
    assert forced.evidence_snapshot is not None
    assert any(
        item.status == "matched"
        for item in forced.evidence_snapshot.evidence_checkpoints
    )

    assert await delete_application(user_id=user_id, session_id=application.session_id)
    assert await get_application(user_id=user_id, session_id=application.session_id) is None

    await storage.close()


def test_local_application_routes_support_detail_edit_refresh_and_delete(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from askpicky.config import settings
    import askpicky.storage as storage_module

    monkeypatch.setattr(settings, "sqlite_db_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "faiss_index_path", tmp_path / "test.faiss")
    monkeypatch.setattr(settings, "generated_dir", tmp_path / "generated")
    monkeypatch.setattr(settings, "demo_user_id", "local-route-user")
    monkeypatch.setattr(storage_module, "_initialised", False)

    from askpicky.api.app import create_app

    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/api/applications/local",
            json={
                "jd_text": """
                Backend Engineer

                Build Python services with FastAPI and PostgreSQL.
                """,
                "company_name": "Route Co",
            },
        )
        assert created.status_code == 201
        session_id = created.json()["application"]["session_id"]

        detail = client.get(f"/api/applications/{session_id}")
        assert detail.status_code == 200
        assert detail.json()["application"]["company_name"] == "Route Co"

        edited = client.patch(
            f"/api/applications/{session_id}",
            json={
                "company_name": "Edited Route Co",
                "role_title": "Edited Backend Engineer",
                "notes": "Review after CV import.",
            },
        )
        assert edited.status_code == 200
        body = edited.json()["application"]
        assert body["company_name"] == "Edited Route Co"
        assert body["role_title"] == "Edited Backend Engineer"
        assert body["notes"] == "Review after CV import."

        refreshed = client.post(f"/api/applications/{session_id}/refresh-evidence")
        assert refreshed.status_code == 200
        assert refreshed.json()["application"]["source"] == "local_jd"

        deleted = client.delete(f"/api/applications/{session_id}")
        assert deleted.status_code == 204

        missing = client.get(f"/api/applications/{session_id}")
        assert missing.status_code == 404
