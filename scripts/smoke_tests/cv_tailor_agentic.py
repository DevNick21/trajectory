"""Smoke test — agentic CV tailor.

Gated behind `SMOKE_AGENTIC_CV=1`. Cost ~$0.35 (Opus xhigh, multi-turn
with ~40k input + ~4k output across turns).

Seeds 20 synthetic career entries in the fresh smoke tempdir SQLite +
FAISS, then runs the agentic path end-to-end against a realistic JD.
Asserts CVOutput validity and that every citation resolves to one of
the seeded entries.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timezone

from ._common import (
    SmokeResult,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "cv_tailor_agentic"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.35
_GATE_ENV = "SMOKE_AGENTIC_CV"


async def _body() -> tuple[list[str], list[str], float]:
    messages: list[str] = []
    failures: list[str] = []

    if os.environ.get(_GATE_ENV, "") != "1":
        messages.append(
            f"skipped — set {_GATE_ENV}=1 to opt into the paid agentic "
            "CV run (~$0.35)"
        )
        return messages, failures, 0.0

    prepare_environment()
    missing = require_anthropic_key()
    if missing:
        return [], [missing], 0.0

    from trajectory.config import settings
    from trajectory.schemas import (
        CareerEntry,
        CompanyResearch,
        ExtractedJobDescription,
        GhostJobAssessment,
        GhostJobJDScore,
        RedFlagsReport,
        ResearchBundle,
        SalarySignals,
        UserProfile,
        WritingStyleProfile,
    )
    from trajectory.storage import insert_career_entry
    from trajectory.sub_agents import cv_tailor_agentic

    settings.enable_agentic_cv_tailor = True

    # Seed a realistic 20-entry career history.
    seeded_ids: list[str] = []
    topics = [
        ("Python observability at scale", "project_note"),
        ("REST API design versioning", "project_note"),
        ("AWS ECS deployment", "project_note"),
        ("incident response pager", "star_polish"),
        ("React component library", "project_note"),
        ("data pipeline Airflow", "project_note"),
        ("LLM evaluation harness", "project_note"),
        ("SRE oncall rotation", "star_polish"),
        ("Postgres migration zero downtime", "project_note"),
        ("team of 4 engineers mentorship", "star_polish"),
        ("Kubernetes cluster upgrade", "project_note"),
        ("feature flag rollout LaunchDarkly", "project_note"),
        ("security audit SOC2", "project_note"),
        ("CI/CD GitHub Actions", "project_note"),
        ("mobile iOS Swift app", "project_note"),
        ("GraphQL federation", "project_note"),
        ("performance profiling Python", "project_note"),
        ("stakeholder communication PM", "star_polish"),
        ("cost optimisation AWS reserved instances", "project_note"),
        ("code review culture retro", "star_polish"),
    ]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i, (topic, kind) in enumerate(topics):
        entry = CareerEntry(
            entry_id=f"smoke_e_{i}",
            user_id="smoke_user",
            kind=kind,
            raw_text=(
                f"{topic}. I led the work end-to-end, delivering "
                "production impact with measurable outcomes. "
                "Specific example: reduced p99 latency from X to Y, "
                "or shipped the feature within Z weeks."
            ),
            created_at=now,
        )
        await insert_career_entry(entry)
        seeded_ids.append(entry.entry_id)
    messages.append(f"seeded {len(seeded_ids)} career entries")

    profile = UserProfile(
        user_id="smoke_user",
        name="Smoke Candidate",
        user_type="uk_resident",
        base_location="London",
        salary_floor=70_000,
        salary_target=95_000,
        target_soc_codes=["2136"],
        linkedin_url="https://linkedin.com/in/smoke",
        github_url="https://github.com/smoke",
        motivations=["impact"],
        deal_breakers=[],
        good_role_signals=["strong engineering culture"],
        life_constraints=[],
        search_started_date=date(2026, 1, 1),
        current_employment="EMPLOYED",
        created_at=now,
        updated_at=now,
    )

    style = WritingStyleProfile(
        profile_id="sp_smoke",
        user_id="smoke_user",
        tone="direct",
        sentence_length_pref="medium",
        formality_level=6,
        hedging_tendency="direct",
        signature_patterns=["starts with verb"],
        avoided_patterns=["passive voice"],
        examples=["Shipped latency wins with observability-first design."],
        source_sample_ids=[],
        sample_count=5,
        created_at=now,
        updated_at=now,
    )

    jd = ExtractedJobDescription(
        role_title="Senior Platform Engineer",
        seniority_signal="senior",
        soc_code_guess="2136",
        soc_code_reasoning="Platform engineering (SOC 2136).",
        location="London",
        remote_policy="hybrid",
        required_skills=["Python", "AWS", "Kubernetes", "observability"],
        posting_platform="company_site",
        hiring_manager_named=True,
        hiring_manager_name="Smoke Hiring",
        jd_text_full=(
            "Senior Platform Engineer. Python + AWS + Kubernetes. "
            "Observability-first culture. You'll own incident response "
            "and drive cost optimisation."
        ),
        specificity_signals=["named_hiring_manager"],
        vagueness_signals=[],
    )

    bundle = ResearchBundle(
        session_id="smoke_session",
        extracted_jd=jd,
        company_research=CompanyResearch(
            company_name="Smoke Co",
            scraped_pages=[],
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
        bundle_completed_at=now,
    )

    try:
        cv = await cv_tailor_agentic.generate(
            jd=jd,
            research_bundle=bundle,
            user=profile,
            retrieved_entries=[],
            style_profile=style,
        )
    except Exception as exc:
        failures.append(f"agentic path raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    # Citation resolution check.
    seeded_set = set(seeded_ids)
    cited: set[str] = set()
    for role in cv.experience:
        for b in role.bullets:
            for c in b.citations:
                if c.kind == "career_entry" and c.entry_id:
                    cited.add(c.entry_id)
    unknown = cited - seeded_set
    if unknown:
        failures.append(f"cited entries not in seed set: {sorted(unknown)}")

    messages.append(
        f"CV: name={cv.name!r} bullets={sum(len(r.bullets) for r in cv.experience)} "
        f"cited_entries={len(cited)}"
    )

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
