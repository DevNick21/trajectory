"""Tests for cv_tailor_agentic + call_agent_with_tools + dispatcher.

Fully mocked — no Anthropic SDK, no FAISS, no SQLite. Exercises:
  - call_agent_with_tools loop mechanics (tool_use → tool_result →
    final emit)
  - CVTailorToolExecutor tracks retrieved_ids
  - Post-hoc hallucination check (cite an un-retrieved entry → raise)
  - Min-3-search rule
  - Dispatcher fallback: agentic raises → legacy runs
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from trajectory.llm import AgentCallFailed
from trajectory.schemas import (
    CareerEntry,
    Citation,
    CompanyResearch,
    CVBullet,
    CVOutput,
    CVRole,
    ExtractedJobDescription,
    GhostJobAssessment,
    GhostJobJDScore,
    RedFlagsReport,
    ResearchBundle,
    SalarySignals,
    UserProfile,
    WritingStyleProfile,
)
from trajectory.sub_agents import cv_tailor_agentic


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user() -> UserProfile:
    n = _now()
    return UserProfile(
        user_id="u1",
        name="Test User",
        user_type="uk_resident",
        base_location="London",
        salary_floor=60000,
        salary_target=80000,
        target_soc_codes=["2136"],
        linkedin_url="https://linkedin.com/in/test",
        motivations=["shipping"],
        deal_breakers=[],
        good_role_signals=[],
        life_constraints=[],
        search_started_date=date(2026, 1, 1),
        current_employment="EMPLOYED",
        created_at=n,
        updated_at=n,
    )


def _entry(entry_id: str, kind: str = "project_note") -> CareerEntry:
    return CareerEntry(
        entry_id=entry_id,
        user_id="u1",
        kind=kind,
        raw_text=f"Entry {entry_id} — built a Python production system with observability.",
        created_at=_now(),
    )


def _style() -> WritingStyleProfile:
    n = _now()
    return WritingStyleProfile(
        profile_id="sp1",
        user_id="u1",
        tone="direct",
        sentence_length_pref="medium",
        formality_level=6,
        hedging_tendency="direct",
        signature_patterns=["starts with verb"],
        avoided_patterns=["passive voice"],
        examples=["Shipped latency improvements."],
        source_sample_ids=[],
        sample_count=5,
        created_at=n,
        updated_at=n,
    )


def _jd() -> ExtractedJobDescription:
    return ExtractedJobDescription(
        role_title="Senior Backend Engineer",
        seniority_signal="senior",
        soc_code_guess="2136",
        soc_code_reasoning="Software role.",
        location="London",
        remote_policy="hybrid",
        required_skills=["Python", "AWS"],
        posting_platform="company_site",
        hiring_manager_named=True,
        hiring_manager_name="Alex",
        jd_text_full="Senior Backend. Python. AWS.",
        specificity_signals=["named_hiring_manager"],
        vagueness_signals=[],
    )


def _bundle() -> ResearchBundle:
    n = _now()
    return ResearchBundle(
        session_id="s1",
        extracted_jd=_jd(),
        company_research=CompanyResearch(
            company_name="Acme Ltd",
            scraped_pages=[],
        ),
        ghost_job=GhostJobAssessment(
            probability="LIKELY_REAL",
            signals=[],
            confidence="HIGH",
            raw_jd_score=GhostJobJDScore(
                named_hiring_manager=1,
                specific_duty_bullets=1,
                specific_tech_stack=1,
                specific_team_context=1,
                specific_success_metrics=1,
                specificity_score=5,
                specificity_signals=[],
                vagueness_signals=[],
            ),
        ),
        salary_signals=SalarySignals(sources_consulted=[], data_citations=[]),
        red_flags=RedFlagsReport(flags=[], checked=True),
        bundle_completed_at=n,
    )


def _cv_output(entry_ids: list[str]) -> CVOutput:
    bullets = [
        CVBullet(
            text=f"[ce:{eid}] Shipped a production Python system.",
            citations=[Citation(kind="career_entry", entry_id=eid)],
        )
        for eid in entry_ids
    ]
    return CVOutput(
        name="Test User",
        contact={"email": "t@x.com"},
        professional_summary=(
            "Senior backend engineer shipping Python systems at scale, "
            "with a track record of observability-first production work "
            "matching this Senior Backend Engineer role at Acme."
        ),
        experience=[
            CVRole(
                title="Senior Engineer",
                company="Prior Co",
                dates="2022-2026",
                bullets=bullets,
            )
        ],
        education=[],
        skills=["Python"],
    )


# ---------------------------------------------------------------------------
# Scripted SDK mock for call_agent_with_tools
# ---------------------------------------------------------------------------


class _Block:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _tool_use(name: str, tool_input: dict, tool_id: str = "tu_x") -> _Block:
    return _Block(type="tool_use", name=name, input=tool_input, id=tool_id)


def _make_response(*blocks, input_tokens: int = 100, output_tokens: int = 50):
    resp = MagicMock()
    resp.content = list(blocks)
    resp.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    resp.stop_reason = "tool_use"
    return resp


# ---------------------------------------------------------------------------
# call_agent_with_tools: happy path — 3 searches + profile + final
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_emits_cv(monkeypatch):
    from trajectory import llm

    # Script: 3 search calls, 1 profile call, then the final emit.
    responses = [
        _make_response(_tool_use(
            "search_career_entries",
            {"query": "Python production observability"},
            tool_id="tu_1",
        )),
        _make_response(_tool_use(
            "search_career_entries",
            {"query": "REST API design"},
            tool_id="tu_2",
        )),
        _make_response(_tool_use(
            "search_career_entries",
            {"query": "AWS infrastructure"},
            tool_id="tu_3",
        )),
        _make_response(_tool_use(
            "get_user_profile_field",
            {"field": "name"},
            tool_id="tu_4",
        )),
        _make_response(_tool_use(
            "emit_structured_output",
            _cv_output(["e1", "e2"]).model_dump(),
            tool_id="tu_final",
        )),
    ]
    call_iter = iter(responses)

    async def fake_create(**kwargs):
        return next(call_iter)

    client = MagicMock()
    client.messages.create = fake_create
    monkeypatch.setattr(llm, "_get_anthropic_client", lambda: client)

    # Fake search returns two entries per call.
    async def fake_search(user_id, query, kind_filter="ANY", top_k=5, **_kw):
        return [_entry("e1"), _entry("e2")]

    monkeypatch.setattr(cv_tailor_agentic, "search_career_entries_semantic", fake_search)

    # Bypass tier1 shield — passthrough.
    async def fake_shield(*, content, source_type, downstream_agent):
        return content, None

    monkeypatch.setattr(cv_tailor_agentic, "shield_content", fake_shield)

    # Bypass cost log.
    async def fake_log_cost(**kwargs):
        pass

    monkeypatch.setattr(llm, "log_llm_cost", fake_log_cost)

    # Bypass credit budget check.
    async def fake_budget(priority):
        pass

    monkeypatch.setattr(llm, "_enforce_credit_budget", fake_budget)

    cv = await cv_tailor_agentic.generate(
        jd=_jd(),
        research_bundle=_bundle(),
        user=_user(),
        retrieved_entries=[],
        style_profile=_style(),
    )
    assert isinstance(cv, CVOutput)
    assert cv.experience[0].bullets[0].text.startswith("[ce:e1]")


# ---------------------------------------------------------------------------
# Hallucination guard: cite an un-retrieved entry → raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hallucinated_citation_raises(monkeypatch):
    from trajectory import llm

    responses = [
        _make_response(_tool_use(
            "search_career_entries", {"query": "a"}, tool_id="tu_1"
        )),
        _make_response(_tool_use(
            "search_career_entries", {"query": "b"}, tool_id="tu_2"
        )),
        _make_response(_tool_use(
            "search_career_entries", {"query": "c"}, tool_id="tu_3"
        )),
        _make_response(_tool_use(
            "emit_structured_output",
            # Cite e1 (real) + e_hallucinated (never retrieved).
            _cv_output(["e1", "e_hallucinated"]).model_dump(),
            tool_id="tu_final",
        )),
    ]
    call_iter = iter(responses)

    async def fake_create(**kwargs):
        return next(call_iter)

    client = MagicMock()
    client.messages.create = fake_create
    monkeypatch.setattr(llm, "_get_anthropic_client", lambda: client)

    async def fake_search(user_id, query, kind_filter="ANY", top_k=5, **_kw):
        return [_entry("e1")]

    monkeypatch.setattr(cv_tailor_agentic, "search_career_entries_semantic", fake_search)

    async def fake_shield(*, content, source_type, downstream_agent):
        return content, None

    monkeypatch.setattr(cv_tailor_agentic, "shield_content", fake_shield)

    async def fake_log_cost(**kwargs):
        pass

    monkeypatch.setattr(llm, "log_llm_cost", fake_log_cost)

    async def fake_budget(priority):
        pass

    monkeypatch.setattr(llm, "_enforce_credit_budget", fake_budget)

    with pytest.raises(AgentCallFailed) as exc:
        await cv_tailor_agentic.generate(
            jd=_jd(),
            research_bundle=_bundle(),
            user=_user(),
            retrieved_entries=[],
            style_profile=_style(),
        )
    assert "not in retrieved set" in str(exc.value)
    assert "e_hallucinated" in str(exc.value)


# ---------------------------------------------------------------------------
# Min-3-search enforcement: emit after 1 search → raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_early_emission_under_min_searches_raises(monkeypatch):
    from trajectory import llm

    responses = [
        _make_response(_tool_use(
            "search_career_entries", {"query": "a"}, tool_id="tu_1"
        )),
        _make_response(_tool_use(
            "emit_structured_output",
            _cv_output(["e1"]).model_dump(),
            tool_id="tu_final",
        )),
    ]
    call_iter = iter(responses)

    async def fake_create(**kwargs):
        return next(call_iter)

    client = MagicMock()
    client.messages.create = fake_create
    monkeypatch.setattr(llm, "_get_anthropic_client", lambda: client)

    async def fake_search(user_id, query, kind_filter="ANY", top_k=5, **_kw):
        return [_entry("e1")]

    monkeypatch.setattr(cv_tailor_agentic, "search_career_entries_semantic", fake_search)

    async def fake_shield(*, content, source_type, downstream_agent):
        return content, None

    monkeypatch.setattr(cv_tailor_agentic, "shield_content", fake_shield)

    async def fake_log_cost(**kwargs):
        pass

    monkeypatch.setattr(llm, "log_llm_cost", fake_log_cost)

    async def fake_budget(priority):
        pass

    monkeypatch.setattr(llm, "_enforce_credit_budget", fake_budget)

    with pytest.raises(AgentCallFailed) as exc:
        await cv_tailor_agentic.generate(
            jd=_jd(),
            research_bundle=_bundle(),
            user=_user(),
            retrieved_entries=[],
            style_profile=_style(),
        )
    assert "minimum is 3" in str(exc.value)


# ---------------------------------------------------------------------------
# Max iterations: loops past 10 without emit → raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_iterations_raises(monkeypatch):
    from trajectory import llm

    # Infinite supply of search tool_uses — never emits final.
    def make_search():
        return _make_response(_tool_use(
            "search_career_entries", {"query": "never ending"}, tool_id="tu_x",
        ))

    async def fake_create(**kwargs):
        return make_search()

    client = MagicMock()
    client.messages.create = fake_create
    monkeypatch.setattr(llm, "_get_anthropic_client", lambda: client)

    async def fake_search(user_id, query, kind_filter="ANY", top_k=5, **_kw):
        return [_entry("e1")]

    monkeypatch.setattr(cv_tailor_agentic, "search_career_entries_semantic", fake_search)

    async def fake_shield(*, content, source_type, downstream_agent):
        return content, None

    monkeypatch.setattr(cv_tailor_agentic, "shield_content", fake_shield)

    async def fake_log_cost(**kwargs):
        pass

    monkeypatch.setattr(llm, "log_llm_cost", fake_log_cost)

    async def fake_budget(priority):
        pass

    monkeypatch.setattr(llm, "_enforce_credit_budget", fake_budget)

    with pytest.raises(AgentCallFailed) as exc:
        await cv_tailor_agentic.generate(
            jd=_jd(),
            research_bundle=_bundle(),
            user=_user(),
            retrieved_entries=[],
            style_profile=_style(),
        )
    assert "max_iterations" in str(exc.value)


# ---------------------------------------------------------------------------
# Dispatcher: flag off → legacy runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_flag_off_calls_legacy(monkeypatch):
    from trajectory.config import settings
    from trajectory.sub_agents import cv_tailor, cv_tailor_legacy

    monkeypatch.setattr(settings, "enable_agentic_cv_tailor", False)

    legacy_called = []

    async def fake_legacy_generate(**kwargs):
        legacy_called.append(True)
        return _cv_output(["e1"])

    monkeypatch.setattr(cv_tailor_legacy, "generate", fake_legacy_generate)

    cv = await cv_tailor.generate(
        jd=_jd(),
        research_bundle=_bundle(),
        user=_user(),
        retrieved_entries=[_entry("e1")],
        style_profile=_style(),
    )
    assert cv.name == "Test User"
    assert legacy_called == [True]


# ---------------------------------------------------------------------------
# Dispatcher: flag on, agentic succeeds → returns agentic output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_flag_on_calls_agentic(monkeypatch):
    from trajectory.config import settings
    from trajectory.sub_agents import cv_tailor, cv_tailor_agentic as agentic_mod

    monkeypatch.setattr(settings, "enable_agentic_cv_tailor", True)

    async def fake_agentic_generate(**kwargs):
        return _cv_output(["agentic_e"])

    monkeypatch.setattr(agentic_mod, "generate", fake_agentic_generate)

    cv = await cv_tailor.generate(
        jd=_jd(),
        research_bundle=_bundle(),
        user=_user(),
        retrieved_entries=[],
        style_profile=_style(),
    )
    assert cv.experience[0].bullets[0].text.startswith("[ce:agentic_e]")


# ---------------------------------------------------------------------------
# Dispatcher: flag on, agentic raises → legacy fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_agentic_fallback_on_error(monkeypatch):
    from trajectory.config import settings
    from trajectory.sub_agents import cv_tailor, cv_tailor_agentic as agentic_mod
    from trajectory.sub_agents import cv_tailor_legacy

    monkeypatch.setattr(settings, "enable_agentic_cv_tailor", True)

    async def bad_agentic(**kwargs):
        raise AgentCallFailed("simulated agentic failure")

    async def fake_legacy(**kwargs):
        return _cv_output(["legacy_e"])

    monkeypatch.setattr(agentic_mod, "generate", bad_agentic)
    monkeypatch.setattr(cv_tailor_legacy, "generate", fake_legacy)

    cv = await cv_tailor.generate(
        jd=_jd(),
        research_bundle=_bundle(),
        user=_user(),
        retrieved_entries=[],
        style_profile=_style(),
    )
    assert cv.experience[0].bullets[0].text.startswith("[ce:legacy_e]")


# ---------------------------------------------------------------------------
# Executor: retrieved_ids + search_call_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_tracks_retrieved_and_count(monkeypatch):
    async def fake_search(user_id, query, kind_filter="ANY", top_k=5, **_kw):
        return [_entry("a"), _entry("b")]

    async def fake_shield(*, content, source_type, downstream_agent):
        return content, None

    monkeypatch.setattr(cv_tailor_agentic, "search_career_entries_semantic", fake_search)
    monkeypatch.setattr(cv_tailor_agentic, "shield_content", fake_shield)

    executor = cv_tailor_agentic.CVTailorToolExecutor(_user(), session_id=None)
    r1 = await executor.execute("search_career_entries", {"query": "x"})
    await executor.execute("search_career_entries", {"query": "y"})
    assert executor.retrieved_ids == {"a", "b"}
    assert executor.search_call_count == 2
    parsed = json.loads(r1)
    assert len(parsed["results"]) == 2

    profile_result = await executor.execute(
        "get_user_profile_field", {"field": "name"}
    )
    assert json.loads(profile_result)["value"] == "Test User"


# ---------------------------------------------------------------------------
# Executor: retrieval budget exhaustion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_enforces_retrieval_budget(monkeypatch):
    call_count = [0]

    async def fake_search(user_id, query, kind_filter="ANY", top_k=5, **_kw):
        call_count[0] += 1
        return [_entry(f"e{call_count[0]}_{i}") for i in range(5)]

    async def fake_shield(*, content, source_type, downstream_agent):
        return content, None

    monkeypatch.setattr(cv_tailor_agentic, "search_career_entries_semantic", fake_search)
    monkeypatch.setattr(cv_tailor_agentic, "shield_content", fake_shield)

    executor = cv_tailor_agentic.CVTailorToolExecutor(_user(), session_id=None)
    # 5 calls × 5 entries each = 25 — exactly at budget.
    for _ in range(5):
        await executor.execute(
            "search_career_entries", {"query": "x", "top_k": 5}
        )
    assert len(executor.retrieved_ids) == 25

    # 6th call should be refused.
    result = await executor.execute(
        "search_career_entries", {"query": "y", "top_k": 5}
    )
    parsed = json.loads(result)
    assert "error" in parsed
    assert "budget exhausted" in parsed["error"]
