"""Regression test for verdict primary/fallback routing."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from askpicky.config import settings
from askpicky.schemas import (
    Citation,
    CompanyResearch,
    CompaniesHouseSnapshot,
    ExtractedJobDescription,
    GhostJobAssessment,
    GhostJobJDScore,
    MotivationFitReport,
    RedFlagsReport,
    ResearchBundle,
    SalarySignals,
    SocCheckResult,
    SponsorStatus,
    UserProfile,
    Verdict,
    VisaStatus,
)
from askpicky.sub_agents import verdict as verdict_agent


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _bundle() -> ResearchBundle:
    return ResearchBundle(
        session_id="s1",
        extracted_jd=ExtractedJobDescription(
            role_title="Senior Software Engineer",
            seniority_signal="senior",
            soc_code_guess="2136",
            soc_code_reasoning="software role",
            salary_band=None,
            location="London",
            remote_policy="hybrid",
            required_years_experience=5,
            required_years_experience_range=[4, 7],
            required_skills=["Python"],
            posted_date=date(2025, 3, 15),
            posting_platform="company_site",
            hiring_manager_named=False,
            jd_text_full="Python role",
            specificity_signals=["Python"],
            vagueness_signals=[],
        ),
        company_research=CompanyResearch(
            company_name="Acme Tech Ltd",
            company_domain="acme.example.com",
            scraped_pages=[],
        ),
        company_identity=None,
        companies_house=CompaniesHouseSnapshot(
            company_number="12345678",
            status="ACTIVE",
            company_name_official="ACME TECH LTD",
            sic_codes=["62012"],
            accounts_overdue=False,
            confirmation_statement_overdue=False,
            no_filings_in_years=0,
        ),
        sponsor_status=SponsorStatus(
            status="LISTED",
            match_confidence=1.0,
            alternative_matches=[],
            register_age_days=1,
            match_path="CRN_VERIFIED",
        ),
        soc_check=SocCheckResult(
            soc_code="2136",
            soc_title="Software engineer",
            below_threshold=False,
            on_appendix_skilled_occupations=True,
            going_rate_gbp=70000,
            new_entrant_rate_gbp=50000,
            shortfall_gbp=0,
            source_status="OK",
        ),
        ghost_job=GhostJobAssessment(
            probability="LIKELY_REAL",
            signals=[],
            confidence="HIGH",
            raw_jd_score=GhostJobJDScore(
                named_hiring_manager=0.0,
                specific_duty_bullets=0.0,
                specific_tech_stack=0.0,
                specific_team_context=0.0,
                specific_success_metrics=0.0,
                specificity_score=0.0,
                specificity_signals=[],
                vagueness_signals=[],
            ),
            age_days=1,
        ),
        salary_signals=SalarySignals(
            ashe=None,
            posted_band=None,
            aggregated_postings=None,
            sources_consulted=[],
            data_citations=[],
        ),
        red_flags=RedFlagsReport(flags=[], checked=True),
        gazette_signals=[],
        bundle_completed_at=_now(),
        sources_truncated=[],
    )


def _user() -> UserProfile:
    now = _now()
    return UserProfile(
        user_id="u1",
        name="Test User",
        user_type="visa_holder",
        visa_status=VisaStatus(route="graduate", expiry_date=date(2026, 9, 30)),
        nationality="Nigerian",
        base_location="London",
        salary_floor=50_000,
        motivations=[],
        deal_breakers=[],
        good_role_signals=[],
        life_constraints=[],
        search_started_date=date(2026, 1, 1),
        current_employment="EMPLOYED",
        created_at=now,
        updated_at=now,
    )


def _verdict() -> Verdict:
    return Verdict(
        decision="GO",
        confidence_pct=78,
        entropy_norm=0.2,
        headline="Apply - strong fit.",
        reasoning=[
            verdict_agent.ReasoningPoint(
                claim="Strong fit.",
                supporting_evidence="evidence",
                citation=Citation(
                    kind="gov_data",
                    data_field="companies_house.status",
                    data_value="ACTIVE",
                ),
            ),
            verdict_agent.ReasoningPoint(
                claim="No blockers.",
                supporting_evidence="evidence",
                citation=Citation(
                    kind="gov_data",
                    data_field="sponsor_register.status",
                    data_value="LISTED",
                ),
            ),
            verdict_agent.ReasoningPoint(
                claim="Good role fit.",
                supporting_evidence="evidence",
                citation=Citation(
                    kind="gov_data",
                    data_field="extracted_jd.required_skills",
                    data_value="Python",
                ),
            ),
        ],
        hard_blockers=[],
        stretch_concerns=[],
        motivation_fit=MotivationFitReport(
            motivation_evaluations=[],
            deal_breaker_evaluations=[],
            good_role_signal_evaluations=[],
        ),
    )


@pytest.mark.asyncio
async def test_verdict_falls_back_to_deepseek_pro(monkeypatch):
    bundle = _bundle()
    user = _user()

    primary_calls: list[dict] = []
    fallback_calls: list[dict] = []

    async def fake_call_agent(**kwargs):
        call_record = {
            "agent_name": kwargs["agent_name"],
            "model": kwargs["model"],
            "attempts": kwargs["max_retries"],
        }
        if kwargs["agent_name"] == "verdict":
            primary_calls.append(call_record)
            raise verdict_agent.BackendError("primary failed", retriable=True)
        fallback_calls.append(call_record)
        return _verdict()

    monkeypatch.setattr(verdict_agent, "call_agent", fake_call_agent)

    result = await verdict_agent.generate(bundle, user, [])

    assert result.decision == "GO"
    assert primary_calls == [
        {"agent_name": "verdict", "model": settings.openai_pro_model_id, "attempts": 2}
    ]
    assert fallback_calls == [
        {"agent_name": "verdict_fallback", "model": settings.deepseek_pro_model_id, "attempts": 2}
    ]
    assert len(result.reasoning) >= 3


@pytest.mark.asyncio
async def test_verdict_raises_when_both_primary_and_fallback_fail(monkeypatch):
    bundle = _bundle()
    user = _user()

    primary_calls: list[dict] = []
    fallback_calls: list[dict] = []

    async def fake_call_agent(**kwargs):
        call_record = {
            "agent_name": kwargs["agent_name"],
            "model": kwargs["model"],
            "attempts": kwargs["max_retries"],
        }
        if kwargs["agent_name"] == "verdict":
            primary_calls.append(call_record)
            raise verdict_agent.AgentCallFailed("primary exhausted retries")
        fallback_calls.append(call_record)
        raise verdict_agent.AgentCallFailed("fallback exhausted retries")

    monkeypatch.setattr(verdict_agent, "call_agent", fake_call_agent)

    with pytest.raises(verdict_agent.AgentCallFailed, match="fallback exhausted retries"):
        await verdict_agent.generate(bundle, user, [])

    assert primary_calls == [
        {"agent_name": "verdict", "model": settings.openai_pro_model_id, "attempts": 2}
    ]
    assert fallback_calls == [
        {"agent_name": "verdict_fallback", "model": settings.deepseek_pro_model_id, "attempts": 2}
    ]
