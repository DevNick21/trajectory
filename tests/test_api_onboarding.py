"""Tests for Wave 9 onboarding API.

Fully mocks the style_extractor + onboarding_parser so tests run
without LLM calls. Covers:

  - /parse: dispatches to the parser and returns its model dump
  - /finalise: writes UserProfile + CareerEntries with the right kinds
  - /finalise fallback when parser returns empty (raw text → 1 entry)
  - /finalise without samples doesn't call style_extractor
  - /finalise with visa_holder derives VisaStatus
  - /finalise when style_extractor raises still completes (profile
    writing_style_profile_id stays None)
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trajectory.schemas import (
    DealBreakersParseResult,
    MotivationsParseResult,
    WritingStyleProfile,
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _style_profile(user_id: str = "demo-user-1") -> WritingStyleProfile:
    now = _now()
    return WritingStyleProfile(
        profile_id="style-pid",
        user_id=user_id,
        tone="direct",
        sentence_length_pref="medium",
        formality_level=6,
        hedging_tendency="direct",
        signature_patterns=["starts with a verb"],
        avoided_patterns=["passive voice"],
        examples=["Shipped observability overhaul."],
        source_sample_ids=[],
        sample_count=2,
        created_at=now,
        updated_at=now,
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


def _valid_finalise_body(**overrides) -> dict:
    body = {
        "name": "Demo User",
        "user_type": "uk_resident",
        "base_location": "London",
        "salary_floor": 60_000,
        "salary_target": 80_000,
        "current_employment": "EMPLOYED",
        "motivations_text": "shipping features that matter",
        "deal_breakers_text": "no remote, micromanagement",
        "good_role_signals_text": "strong engineering culture",
        "life_constraints": [],
        "writing_samples": [],
        "career_narrative": "",
    }
    body.update(overrides)
    return body


def _patch_style_extractor(monkeypatch, *, raises: bool = False):
    from trajectory.sub_agents import style_extractor

    async def fake(user_id, samples, session_id=None):
        if raises:
            raise RuntimeError("style extractor boom")
        return _style_profile(user_id)

    monkeypatch.setattr(style_extractor, "extract", fake)


def _patch_parser(monkeypatch, *, motivations=None, deal_breakers=None):
    """Mock the onboarding_parser.parse_stage dispatcher.

    `motivations` / `deal_breakers` arguments let individual tests
    dictate what the parser returns for each voice stage. None means
    "use the real parse result for that stage" — but we'll never have
    a real LLM call in a test; leaving the arg None yields None
    (simulates parser failure → fallback to raw text).
    """
    from trajectory.sub_agents import onboarding_parser

    async def fake(stage, text):
        if stage == "motivations":
            return motivations
        if stage == "deal_breakers":
            return deal_breakers
        return None

    monkeypatch.setattr(onboarding_parser, "parse_stage", fake)


# ---------------------------------------------------------------------------
# /parse
# ---------------------------------------------------------------------------


def test_parse_returns_parser_output(client, monkeypatch):
    from trajectory.sub_agents import onboarding_parser

    captured = {}

    async def fake(stage, text):
        captured["stage"] = stage
        captured["text"] = text
        return MotivationsParseResult(
            status="parsed",
            motivations=["impact", "autonomy"],
            drains=["micromanagement"],
        )

    monkeypatch.setattr(onboarding_parser, "parse_stage", fake)

    resp = client.post(
        "/api/onboarding/parse",
        json={"stage": "motivations", "text": "I want impact and autonomy."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "parsed"
    assert body["motivations"] == ["impact", "autonomy"]
    assert captured == {
        "stage": "motivations",
        "text": "I want impact and autonomy.",
    }


def test_parse_422_for_unknown_stage(client, monkeypatch):
    _patch_parser(monkeypatch)
    resp = client.post(
        "/api/onboarding/parse",
        json={"stage": "not_a_stage", "text": "x"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /finalise — happy path
# ---------------------------------------------------------------------------


def test_finalise_writes_profile_and_entries(client, monkeypatch):
    _patch_style_extractor(monkeypatch)
    _patch_parser(
        monkeypatch,
        motivations=MotivationsParseResult(
            status="parsed",
            motivations=["impact", "autonomy"],
            drains=["meetings"],
        ),
        deal_breakers=DealBreakersParseResult(
            status="parsed",
            deal_breakers=["no remote"],
            good_role_signals=["strong culture"],
        ),
    )

    resp = client.post(
        "/api/onboarding/finalise",
        json=_valid_finalise_body(writing_samples=["Sample A", "Sample B"]),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user_id"] == "demo-user-1"
    assert body["writing_style_profile_id"] == "style-pid"

    # Profile persisted.
    from trajectory.storage import get_user_profile, get_all_career_entries_for_user

    user = _seed(get_user_profile("demo-user-1"))
    assert user is not None
    assert user.name == "Demo User"
    assert user.base_location == "London"
    assert user.salary_floor == 60_000
    assert user.motivations == ["impact", "autonomy"]
    assert user.deal_breakers == ["no remote"]
    # good_role_signals comes from parser + extra signals text.
    assert "strong culture" in user.good_role_signals
    assert "strong engineering culture" in user.good_role_signals
    # drains from parser appended as life_constraints.
    assert "meetings" in user.life_constraints

    entries = _seed(get_all_career_entries_for_user("demo-user-1"))
    kinds = [e.kind for e in entries]
    # motivations=2, deal_breakers=1, good_role_signals=2, writing_samples=2.
    assert kinds.count("motivation") == 2
    assert kinds.count("deal_breaker") == 1
    assert kinds.count("good_role_signal") == 2
    assert kinds.count("writing_sample") == 2


def test_finalise_fallback_when_parser_returns_none(client, monkeypatch):
    """Parser None → raw text becomes a single-item list."""
    _patch_style_extractor(monkeypatch)
    _patch_parser(monkeypatch, motivations=None, deal_breakers=None)

    resp = client.post(
        "/api/onboarding/finalise",
        json=_valid_finalise_body(
            motivations_text="impact and culture",
            deal_breakers_text="no remote",
        ),
    )
    assert resp.status_code == 201

    from trajectory.storage import get_user_profile

    user = _seed(get_user_profile("demo-user-1"))
    assert user is not None
    assert user.motivations == ["impact and culture"]
    assert user.deal_breakers == ["no remote"]


def test_finalise_without_samples_skips_style_extractor(client, monkeypatch):
    called = {"n": 0}

    async def fake(user_id, samples, session_id=None):
        called["n"] += 1
        return _style_profile(user_id)

    from trajectory.sub_agents import style_extractor

    monkeypatch.setattr(style_extractor, "extract", fake)
    _patch_parser(monkeypatch)

    resp = client.post(
        "/api/onboarding/finalise",
        json=_valid_finalise_body(writing_samples=[]),
    )
    assert resp.status_code == 201
    assert called["n"] == 0
    assert resp.json()["writing_style_profile_id"] is None


def test_finalise_style_extractor_failure_is_graceful(client, monkeypatch):
    _patch_style_extractor(monkeypatch, raises=True)
    _patch_parser(monkeypatch)

    resp = client.post(
        "/api/onboarding/finalise",
        json=_valid_finalise_body(writing_samples=["x"]),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["writing_style_profile_id"] is None


def test_finalise_visa_holder_derives_visa_status(client, monkeypatch):
    _patch_style_extractor(monkeypatch)
    _patch_parser(monkeypatch)

    resp = client.post(
        "/api/onboarding/finalise",
        json=_valid_finalise_body(
            user_type="visa_holder",
            visa_route="graduate",
            visa_expiry=str(date(2027, 12, 31)),
            nationality="Nigerian",
        ),
    )
    assert resp.status_code == 201

    from trajectory.storage import get_user_profile

    user = _seed(get_user_profile("demo-user-1"))
    assert user is not None
    assert user.user_type == "visa_holder"
    assert user.visa_status is not None
    assert user.visa_status.route == "graduate"
    assert user.visa_status.expiry_date == date(2027, 12, 31)
    assert user.nationality == "Nigerian"


def test_finalise_visa_holder_with_past_expiry_uses_fallback(client, monkeypatch):
    """Matches the bot's behaviour — expired date → 2 years from now."""
    _patch_style_extractor(monkeypatch)
    _patch_parser(monkeypatch)

    resp = client.post(
        "/api/onboarding/finalise",
        json=_valid_finalise_body(
            user_type="visa_holder",
            visa_route="skilled_worker",
            visa_expiry=str(date(2020, 1, 1)),
        ),
    )
    assert resp.status_code == 201

    from trajectory.storage import get_user_profile

    user = _seed(get_user_profile("demo-user-1"))
    assert user is not None
    assert user.visa_status is not None
    assert user.visa_status.expiry_date.year == date.today().year + 2


def test_finalise_422_for_bad_payload(client):
    # Missing required name.
    body = _valid_finalise_body()
    body.pop("name")
    resp = client.post("/api/onboarding/finalise", json=body)
    assert resp.status_code == 422
