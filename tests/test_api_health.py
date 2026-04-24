"""Tests for the FastAPI health endpoint + lifespan wiring.

Wave 2 of MIGRATION_PLAN.md. Validates that the app constructs, the
lifespan attaches Storage to app.state, and `/health` returns the
documented payload shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """Build a fresh app per test against a per-test SQLite tempdir."""
    from trajectory.config import settings

    # Redirect storage paths so tests never touch the real DB / FAISS.
    monkeypatch.setattr(settings, "sqlite_db_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "faiss_index_path", tmp_path / "test.faiss")

    from trajectory.api.app import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health_returns_200_with_expected_shape(client):
    resp = client.get("/health")
    assert resp.status_code == 200

    body = resp.json()
    for required in (
        "status",
        "service",
        "version",
        "storage_initialised",
        "demo_user_id_configured",
    ):
        assert required in body, f"missing field {required!r} in {body}"

    assert body["status"] == "ok"
    assert body["service"] == "trajectory.api"
    assert body["storage_initialised"] is True


def test_health_reports_demo_user_id_configured_state(client, monkeypatch):
    """The flag flips with settings.demo_user_id."""
    from trajectory.config import settings

    monkeypatch.setattr(settings, "demo_user_id", "")
    body = client.get("/health").json()
    assert body["demo_user_id_configured"] is False

    monkeypatch.setattr(settings, "demo_user_id", "12345")
    body = client.get("/health").json()
    assert body["demo_user_id_configured"] is True


def test_unknown_route_returns_404(client):
    resp = client.get("/this-does-not-exist")
    assert resp.status_code == 404


def test_cors_header_present_for_configured_origin(client):
    """CORS allows the configured origin and rejects others (no
    wildcards per MIGRATION_PLAN.md §6 risk #9)."""
    from trajectory.config import settings

    resp = client.options(
        "/health",
        headers={
            "Origin": settings.web_origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    # Allowed origin → preflight succeeds (200 or 204).
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == settings.web_origin


def test_cors_rejects_disallowed_origin(client):
    resp = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Disallowed origin → no allow-origin header echoed back.
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example.com"
