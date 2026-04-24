"""Tests for src/trajectory/managed/company_investigator.py.

Fully mocked — no Anthropic SDK calls, no network, no file system
(cache redirected to a tempdir). Exercises the integration by scripting
an event stream through `_events.consume_stream` and asserting the
end-to-end conversion, citation validation, archive/delete lifecycle,
and Content Shield invocation.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from trajectory.managed import _resources
from trajectory.managed.company_investigator import (
    ManagedInvestigatorFailed,
    investigate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_JOB_URL = "https://example.com/jobs/senior-engineer"
_CAREERS_URL = "https://example.com/careers"
_ABOUT_URL = "https://example.com/about"


def _extracted_jd_dict() -> dict:
    return {
        "role_title": "Senior Backend Engineer",
        "seniority_signal": "senior",
        "soc_code_guess": "2136",
        "soc_code_reasoning": "Software development role (SOC 2020 2136).",
        "salary_band": None,
        "location": "London",
        "remote_policy": "hybrid",
        "required_years_experience": 5,
        "required_years_experience_range": None,
        "required_skills": ["Python", "AWS"],
        "posted_date": "2026-04-15",
        "posting_platform": "company_site",
        "hiring_manager_named": True,
        "hiring_manager_name": "Alex Fernandez",
        "jd_text_full": "Senior Backend role. Python. AWS. 5+ years.",
        "specificity_signals": ["named hiring manager"],
        "vagueness_signals": [],
    }


def _investigator_output_json(culture_snippet: str) -> str:
    payload = {
        "company_name": "Example Ltd",
        "company_domain": "example.com",
        "culture_claims": [
            {
                "claim": "Culture values deep focus.",
                "source_url": _ABOUT_URL,
                "verbatim_snippet": culture_snippet,
            }
        ],
        "tech_stack_signals": [],
        "team_size_signals": [],
        "recent_activity_signals": [],
        "posted_salary_bands": [],
        "careers_page_url": _CAREERS_URL,
        "not_on_careers_page": False,
        "extracted_jd": _extracted_jd_dict(),
        "investigation_notes": "Fetched JD, careers, and about page.",
    }
    return json.dumps(payload)


class _FakeEvent:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get(self, key, default=None):
        return getattr(self, key, default)


class _FakeStream:
    """Async context manager yielding a scripted sequence of events."""

    def __init__(self, events: list[_FakeEvent]):
        self._events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def __aiter__(self):
        self._iter = iter(self._events)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def _build_mock_client(
    events: list[_FakeEvent],
    *,
    session_usage_input: int = 1200,
    session_usage_output: int = 800,
) -> MagicMock:
    """Construct a mock AsyncAnthropic client with the beta namespace."""
    client = MagicMock()

    # Agent + environment
    client.beta.agents.create = AsyncMock(
        return_value=MagicMock(id="agt_fake", version=1)
    )
    client.beta.environments.create = AsyncMock(
        return_value=MagicMock(id="env_fake")
    )

    # Session lifecycle
    client.beta.sessions.create = AsyncMock(return_value=MagicMock(id="sesn_fake"))
    client.beta.sessions.archive = AsyncMock(return_value=None)
    client.beta.sessions.delete = AsyncMock(return_value=None)

    # Usage retrieval
    retrieved = MagicMock()
    retrieved.usage = MagicMock(
        input_tokens=session_usage_input,
        output_tokens=session_usage_output,
    )
    client.beta.sessions.retrieve = AsyncMock(return_value=retrieved)

    # Events. AsyncAnthropic's events.stream(...) is an async def that
    # resolves to the async context manager — match that shape with
    # AsyncMock so the production `async with await ...` pattern works.
    client.beta.sessions.events.send = AsyncMock(return_value=None)

    stream = _FakeStream(events)
    client.beta.sessions.events.stream = AsyncMock(return_value=stream)

    return client


@pytest.fixture(autouse=True)
def _redirect_cache(tmp_path: Path, monkeypatch):
    """Every test gets a fresh empty cache in tmp_path."""
    monkeypatch.setattr(_resources, "_CACHE_PATH", tmp_path / "managed_agents.json")
    yield


@pytest.fixture
def mock_anthropic(monkeypatch):
    """Monkeypatch `AsyncAnthropic` inside company_investigator so
    `from anthropic import AsyncAnthropic` returns our mock."""
    import anthropic

    def _inject(client_instance):
        class _FakeAsyncAnthropic:
            def __init__(self, *args, **kwargs):
                # Return our pre-configured client by making this a
                # singleton-style factory.
                pass

            def __new__(cls, *args, **kwargs):
                return client_instance

        monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeAsyncAnthropic)

    return _inject


@pytest.fixture(autouse=True)
def _no_shield_tier2(monkeypatch):
    """Bypass Tier 2 Sonnet calls — smoke-test-shaped tier1 only."""
    from trajectory.validators import content_shield

    async def _fake_shield(*, content, source_type, downstream_agent):
        # Return cleaned text as-is (tier1 passthrough), no verdict.
        return content, None

    monkeypatch.setattr(content_shield, "shield", _fake_shield)


@pytest.fixture(autouse=True)
def _no_cost_log(monkeypatch):
    """Sidestep the SQLite cost log — tests run with no DB."""
    from trajectory.managed import company_investigator

    logged = []

    async def _fake_log(**kwargs):
        logged.append(kwargs)

    monkeypatch.setattr(company_investigator, "log_llm_cost", _fake_log)
    return logged


# ---------------------------------------------------------------------------
# Scenario: successful investigation
# ---------------------------------------------------------------------------


def _happy_path_events() -> list[_FakeEvent]:
    """Scripted sequence: 2 web_fetch calls then final JSON then idle."""
    culture_snippet = "We hire for deep focus and long attention spans."
    final_msg = _investigator_output_json(culture_snippet)

    return [
        # First web_fetch: the JD page
        _FakeEvent(
            type="agent.tool_use",
            name="web_fetch",
            id="tu_1",
            input={"url": _JOB_URL},
        ),
        _FakeEvent(
            type="agent.tool_result",
            tool_use_id="tu_1",
            content=[
                {"type": "text", "text": f"Job description body text for {_JOB_URL}."}
            ],
        ),
        # Second web_fetch: the about page
        _FakeEvent(
            type="agent.tool_use",
            name="web_fetch",
            id="tu_2",
            input={"url": _ABOUT_URL},
        ),
        _FakeEvent(
            type="agent.tool_result",
            tool_use_id="tu_2",
            content=[
                {
                    "type": "text",
                    "text": (
                        f"About Example Ltd. {culture_snippet} "
                        "Founded 2019."
                    ),
                }
            ],
        ),
        # Span usage event
        _FakeEvent(
            type="span.model_request_end",
            model_usage=MagicMock(input_tokens=500, output_tokens=300),
        ),
        # Final agent.message with the JSON
        _FakeEvent(
            type="agent.message",
            content=[{"type": "text", "text": final_msg}],
        ),
        # Terminate
        _FakeEvent(type="session.status_idle"),
    ]


@pytest.mark.asyncio
async def test_happy_path_returns_company_research(mock_anthropic, _no_cost_log):
    client = _build_mock_client(_happy_path_events())
    mock_anthropic(client)

    research, extracted_jd = await investigate(
        job_url=_JOB_URL, session_id="traj-session-xyz"
    )

    assert research.company_name == "Example Ltd"
    assert research.company_domain == "example.com"
    assert len(research.culture_claims) == 1
    assert research.culture_claims[0].url == _ABOUT_URL
    assert extracted_jd.role_title == "Senior Backend Engineer"
    assert extracted_jd.posted_date == date(2026, 4, 15)

    # Session archived (happy path) and retrieve called for usage.
    client.beta.sessions.archive.assert_called_once_with("sesn_fake")
    client.beta.sessions.delete.assert_not_called()
    client.beta.sessions.retrieve.assert_called_once_with("sesn_fake")

    # Cost log fired once with authoritative session totals.
    assert len(_no_cost_log) == 1
    logged = _no_cost_log[0]
    assert logged["agent_name"] == "managed_company_investigator"
    assert logged["input_tokens"] == 1200
    assert logged["output_tokens"] == 800


# ---------------------------------------------------------------------------
# Scenario: verbatim snippet not present in any fetched page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paraphrased_snippet_raises_and_deletes(mock_anthropic):
    """Citation not found in any fetched page → ManagedInvestigatorFailed
    and session.delete called (not archive)."""
    # Snippet the agent claims was in the page, but isn't.
    events = _happy_path_events()
    # Replace the final JSON with one whose snippet doesn't appear in
    # the about-page text.
    events[-2] = _FakeEvent(
        type="agent.message",
        content=[{
            "type": "text",
            "text": _investigator_output_json(
                "Invented paraphrase that doesn't appear anywhere.",
            ),
        }],
    )
    client = _build_mock_client(events)
    mock_anthropic(client)

    with pytest.raises(ManagedInvestigatorFailed) as exc_info:
        await investigate(job_url=_JOB_URL)
    assert "verbatim_snippet not found" in str(exc_info.value)

    client.beta.sessions.delete.assert_called_once_with("sesn_fake")
    client.beta.sessions.archive.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario: session terminates early
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_early_termination_raises_and_deletes(mock_anthropic):
    events = [
        _FakeEvent(
            type="agent.tool_use",
            name="web_fetch",
            id="tu_1",
            input={"url": _JOB_URL},
        ),
        _FakeEvent(
            type="session.status_terminated",
            error=MagicMock(message="sandbox crashed"),
        ),
    ]
    client = _build_mock_client(events)
    mock_anthropic(client)

    with pytest.raises(ManagedInvestigatorFailed) as exc_info:
        await investigate(job_url=_JOB_URL)
    assert "terminated early" in str(exc_info.value)

    client.beta.sessions.delete.assert_called_once_with("sesn_fake")
    client.beta.sessions.archive.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario: no final JSON emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_final_json_raises(mock_anthropic):
    events = [
        _FakeEvent(
            type="agent.tool_use",
            name="web_fetch",
            id="tu_1",
            input={"url": _JOB_URL},
        ),
        _FakeEvent(
            type="agent.tool_result",
            tool_use_id="tu_1",
            content=[{"type": "text", "text": "JD body."}],
        ),
        _FakeEvent(type="session.status_idle"),
    ]
    client = _build_mock_client(events)
    mock_anthropic(client)

    with pytest.raises(ManagedInvestigatorFailed) as exc_info:
        await investigate(job_url=_JOB_URL)
    assert "parseable JSON" in str(exc_info.value)

    client.beta.sessions.delete.assert_called_once_with("sesn_fake")


# ---------------------------------------------------------------------------
# Scenario: Content Shield rejects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shield_reject_raises_and_deletes(mock_anthropic, monkeypatch):
    """REJECT verdict on a scraped page → investigator raises + deletes."""
    from trajectory.managed import company_investigator
    from trajectory.schemas import ContentShieldVerdict

    reject_verdict = ContentShieldVerdict(
        classification="MALICIOUS",
        reasoning="prompt injection detected",
        residual_patterns_detected=["role_switch"],
        recommended_action="REJECT",
    )

    async def _reject_shield(*, content, source_type, downstream_agent):
        return content, reject_verdict

    monkeypatch.setattr(company_investigator, "shield_content", _reject_shield)

    client = _build_mock_client(_happy_path_events())
    mock_anthropic(client)

    with pytest.raises(ManagedInvestigatorFailed) as exc_info:
        await investigate(job_url=_JOB_URL)
    assert "content shield rejected" in str(exc_info.value)

    client.beta.sessions.delete.assert_called_once_with("sesn_fake")
    client.beta.sessions.archive.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario: resource caching — second call does not recreate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resource_reuse_across_invocations(mock_anthropic, _no_cost_log):
    """Two successive investigations reuse the same agent + environment."""
    client = _build_mock_client(_happy_path_events())
    mock_anthropic(client)
    await investigate(job_url=_JOB_URL)

    # Reset the stream for a second run (fresh scripted events).
    # AsyncMock — events.stream is an async def on the real SDK.
    client.beta.sessions.events.stream = AsyncMock(
        return_value=_FakeStream(_happy_path_events())
    )
    client.beta.sessions.archive.reset_mock()
    await investigate(job_url=_JOB_URL)

    # agents.create fired once; second call hit cache.
    assert client.beta.agents.create.call_count == 1
    assert client.beta.environments.create.call_count == 1
    # Sessions created twice (one per investigate() call).
    assert client.beta.sessions.create.call_count == 2


# ---------------------------------------------------------------------------
# Scenario: final JSON wrapped in markdown fences still parses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_markdown_fenced_json_is_tolerated(mock_anthropic, _no_cost_log):
    events = _happy_path_events()
    # Wrap the final JSON in ```json fences.
    original_text = events[-2].content[0]["text"]
    events[-2] = _FakeEvent(
        type="agent.message",
        content=[{"type": "text", "text": f"```json\n{original_text}\n```"}],
    )
    client = _build_mock_client(events)
    mock_anthropic(client)

    research, _ = await investigate(job_url=_JOB_URL)
    assert research.company_name == "Example Ltd"
