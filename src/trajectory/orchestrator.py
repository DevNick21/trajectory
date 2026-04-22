"""Top-level pipeline coordination.

Implements all intent handlers. Bot handlers call into this module.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .config import settings
from .schemas import (
    CareerEntry,
    CoverLetterOutput,
    CVOutput,
    DraftReplyOutput,
    ExtractedJobDescription,
    JobSearchContext,
    LikelyQuestionsOutput,
    Pack,
    ResearchBundle,
    SalaryRecommendation,
    Session,
    STARPolish,
    UserProfile,
    Verdict,
    WritingStyleProfile,
)
from .storage import Storage
from .validators.citations import validate_output as validate_citations  # noqa: F401

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase 1 — Research + Verdict
# ---------------------------------------------------------------------------


async def handle_forward_job(
    job_url: str,
    user: UserProfile,
    session: Session,
    storage: Storage,
    bot=None,
    chat_id: Optional[int] = None,
    message_id: Optional[int] = None,
) -> tuple[ResearchBundle, Verdict]:
    """Run Phase 1 (8 sub-agents) + Phase 2 (verdict). Returns bundle + verdict."""
    from .sub_agents import (
        company_scraper,
        companies_house as ch_agent,
        reviews as rev_agent,
        red_flags as rf_agent,
        ghost_job_detector,
        salary_data as sal_agent,
        sponsor_register as sr_agent,
        soc_check as soc_agent,
        verdict as verdict_agent,
    )
    from .bot.progress_stream import PhaseOneProgressStreamer

    all_agents = [
        "phase_1_jd_extractor",
        "phase_1_company_scraper_summariser",
        "companies_house",
        "reviews",
        "phase_1_ghost_job_jd_scorer",
        "salary_data",
        "sponsor_register",
        "soc_check",
        "phase_1_red_flags",
    ]

    streamer: Optional[PhaseOneProgressStreamer] = None
    if bot and chat_id and message_id:
        streamer = PhaseOneProgressStreamer(
            bot=bot,
            chat_id=chat_id,
            message_id=message_id,
            all_agents=all_agents,
        )

    async def mark(name: str) -> None:
        if streamer:
            await streamer.mark_complete(name)

    # ── Phase 1A: company scraper (JD + company research, serial) ─────────
    log.info("Phase 1A: company_scraper for %s", job_url)
    company_research, jd = await company_scraper.run(
        job_url=job_url, session_id=session.session_id
    )
    await mark("phase_1_jd_extractor")
    await mark("phase_1_company_scraper_summariser")

    # Cache scraped pages from company_research
    for page in company_research.scraped_pages:
        await storage.cache_scraped_page(page.url, page.text, page.fetched_at)

    # ── Phase 1B: companies house (fast, needed by ghost detector) ─────────
    log.info("Phase 1B: companies_house")
    ch_snapshot = None
    try:
        ch_snapshot = await ch_agent.lookup(
            company_name=company_research.company_name,
        )
        await mark("companies_house")
    except Exception as exc:
        log.warning("companies_house failed: %s", exc)
        await mark("companies_house")

    # ── Phase 1C: remaining agents in parallel ─────────────────────────────
    log.info("Phase 1C: parallel agents")

    async def run_reviews():
        try:
            result = await rev_agent.fetch(
                company_name=company_research.company_name,
            )
            await mark("reviews")
            return result
        except Exception as exc:
            log.warning("reviews failed: %s", exc)
            await mark("reviews")
            return []

    async def run_salary():
        try:
            result = await sal_agent.fetch(
                role=jd.role_title,
                location=jd.location,
                soc_code=jd.soc_code_guess,
                posted_band=dict(jd.salary_band) if jd.salary_band else None,
            )
            await mark("salary_data")
            return result
        except Exception as exc:
            log.warning("salary_data failed: %s", exc)
            await mark("salary_data")
            from .schemas import SalarySignals
            return SalarySignals(sources_consulted=[], data_citations=[])

    async def run_sponsor():
        if user.user_type != "visa_holder":
            await mark("sponsor_register")
            return None
        try:
            result = await sr_agent.lookup(
                company_name=company_research.company_name,
            )
            await mark("sponsor_register")
            return result
        except Exception as exc:
            log.warning("sponsor_register failed: %s", exc)
            await mark("sponsor_register")
            return None

    async def run_soc():
        if user.user_type != "visa_holder":
            await mark("soc_check")
            return None
        try:
            result = await soc_agent.verify(jd=jd, user=user)
            await mark("soc_check")
            return result
        except Exception as exc:
            log.warning("soc_check failed: %s", exc)
            await mark("soc_check")
            return None

    async def run_ghost():
        try:
            result = await ghost_job_detector.score(
                jd=jd,
                company_research=company_research,
                companies_house=ch_snapshot,
                session_id=session.session_id,
            )
            await mark("phase_1_ghost_job_jd_scorer")
            return result
        except Exception as exc:
            log.warning("ghost_job_detector failed: %s", exc)
            await mark("phase_1_ghost_job_jd_scorer")
            raise

    async def run_red_flags():
        try:
            result = await rf_agent.detect(
                company_research=company_research,
                companies_house=ch_snapshot,
                reviews=[],
                session_id=session.session_id,
            )
            await mark("phase_1_red_flags")
            return result
        except Exception as exc:
            log.warning("red_flags failed: %s", exc)
            await mark("phase_1_red_flags")
            from .schemas import RedFlagsReport
            return RedFlagsReport(flags=[], checked=True)

    (
        review_excerpts,
        salary_signals,
        sponsor_status,
        soc_result,
        ghost_assessment,
        red_flags_report,
    ) = await asyncio.gather(
        run_reviews(),
        run_salary(),
        run_sponsor(),
        run_soc(),
        run_ghost(),
        run_red_flags(),
        return_exceptions=False,
    )

    if streamer:
        await streamer.flush()

    bundle = ResearchBundle(
        session_id=session.session_id,
        extracted_jd=jd,
        company_research=company_research,
        companies_house=ch_snapshot,
        sponsor_status=sponsor_status,
        soc_check=soc_result,
        ghost_job=ghost_assessment,
        salary_signals=salary_signals,
        red_flags=red_flags_report,
        bundle_completed_at=datetime.utcnow(),
    )

    await storage.save_phase1_output(session.session_id, bundle)

    # ── Phase 2: Verdict ───────────────────────────────────────────────────
    log.info("Phase 2: verdict")
    retrieved = await storage.retrieve_relevant_entries(
        user_id=user.user_id,
        query=f"{jd.role_title} {' '.join(jd.required_skills[:5])}",
        k=8,
    )

    verdict = await verdict_agent.generate(
        research_bundle=bundle,
        user=user,
        retrieved_entries=retrieved,
        session_id=session.session_id,
    )

    await storage.save_verdict(session.session_id, verdict)
    return bundle, verdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_session_bundle(
    session: Session, storage: Storage
) -> Optional[ResearchBundle]:
    if session.phase1_output:
        return ResearchBundle.model_validate(session.phase1_output)
    return None


async def _get_style_profile(
    user: UserProfile, storage: Storage
) -> Optional[WritingStyleProfile]:
    return await storage.get_writing_style_profile(user.user_id)


async def _audit_and_ship(
    generated,
    research_bundle: Optional[ResearchBundle],
    style_profile: WritingStyleProfile,
    company_name: str,
    generator_coro,
    session_id: Optional[str] = None,
):
    """Run self-audit; apply rewrites or re-run generator on HARD_REJECT."""
    from .sub_agents import self_audit

    audit = await self_audit.run(
        generated=generated,
        research_bundle=research_bundle,
        style_profile=style_profile,
        company_name=company_name,
        session_id=session_id,
    )

    if not audit.flags:
        return generated

    if audit.hard_reject:
        log.warning("Self-audit HARD_REJECT — re-running generator")
        try:
            regenerated = await generator_coro()
            return regenerated
        except Exception as exc:
            log.error("Generator re-run failed: %s", exc)
            return generated

    # Non-fatal flags: apply rewrites to text fields
    log.info("Self-audit: %d flags — applying rewrites", len(audit.flags))
    try:
        import json as _json
        raw = _json.dumps(generated.model_dump(mode="json"))
        for flag in audit.flags:
            if flag.offending_substring and flag.proposed_rewrite:
                raw = raw.replace(flag.offending_substring, flag.proposed_rewrite, 1)
        patched = generated.__class__.model_validate_json(raw)
        return patched
    except Exception as exc:
        log.warning("Rewrite application failed: %s — shipping original", exc)
        return generated


def _make_output_paths(session_id: str, kind: str) -> tuple[Path, Path]:
    out_dir = settings.generated_dir / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{kind}.docx", out_dir / f"{kind}.pdf"


# ---------------------------------------------------------------------------
# Phase 4 handlers
# ---------------------------------------------------------------------------


async def handle_draft_cv(
    session: Session,
    user: UserProfile,
    storage: Storage,
    star_polishes: Optional[list[STARPolish]] = None,
) -> tuple[CVOutput, Path, Path]:
    from .sub_agents import cv_tailor
    from .renderers.cv_docx import render as render_docx
    from .renderers.cv_pdf import render as render_pdf

    bundle = await _load_session_bundle(session, storage)
    style_profile = await _get_style_profile(user, storage)

    jd = bundle.extracted_jd if bundle else None
    query = f"{jd.role_title} {' '.join((jd.required_skills or [])[:5])}" if jd else user.motivations[0] if user.motivations else "software engineer"
    retrieved = await storage.retrieve_relevant_entries(user_id=user.user_id, query=query, k=12)

    if style_profile is None:
        style_profile = _fallback_style()

    company_name = bundle.company_research.company_name if bundle else "the company"

    async def generator():
        return await cv_tailor.generate(
            jd=bundle.extracted_jd,
            research_bundle=bundle,
            user=user,
            retrieved_entries=retrieved,
            style_profile=style_profile,
            star_material=star_polishes,
        )

    cv = await generator()
    cv = await _audit_and_ship(cv, bundle, style_profile, company_name, generator, session.session_id)

    docx_path, pdf_path = _make_output_paths(session.session_id, "cv")
    render_docx(cv, docx_path)
    render_pdf(cv, pdf_path)

    return cv, docx_path, pdf_path


async def handle_draft_cover_letter(
    session: Session,
    user: UserProfile,
    storage: Storage,
    star_polishes: Optional[list[STARPolish]] = None,
) -> tuple[CoverLetterOutput, Path, Path]:
    from .sub_agents import cover_letter
    from .renderers.cover_letter_docx import render as render_docx
    from .renderers.cover_letter_pdf import render as render_pdf

    bundle = await _load_session_bundle(session, storage)
    style_profile = await _get_style_profile(user, storage) or _fallback_style()

    jd = bundle.extracted_jd if bundle else None
    query = f"{jd.role_title} cover letter" if jd else "cover letter"
    retrieved = await storage.retrieve_relevant_entries(user_id=user.user_id, query=query, k=10)

    company_name = bundle.company_research.company_name if bundle else "the company"

    async def generator():
        return await cover_letter.generate(
            jd=bundle.extracted_jd,
            research_bundle=bundle,
            user=user,
            retrieved_entries=retrieved,
            style_profile=style_profile,
            star_material=star_polishes,
        )

    cl = await generator()
    cl = await _audit_and_ship(cl, bundle, style_profile, company_name, generator, session.session_id)

    docx_path, pdf_path = _make_output_paths(session.session_id, "cover_letter")
    render_docx(cl, docx_path)
    render_pdf(cl, pdf_path)

    return cl, docx_path, pdf_path


async def handle_predict_questions(
    session: Session,
    user: UserProfile,
    storage: Storage,
) -> LikelyQuestionsOutput:
    from .sub_agents import likely_questions

    bundle = await _load_session_bundle(session, storage)
    style_profile = await _get_style_profile(user, storage) or _fallback_style()

    jd = bundle.extracted_jd if bundle else None
    query = f"{jd.role_title} interview" if jd else "interview questions"
    retrieved = await storage.retrieve_relevant_entries(user_id=user.user_id, query=query, k=10)

    company_name = bundle.company_research.company_name if bundle else "the company"

    async def generator():
        return await likely_questions.generate(
            jd=bundle.extracted_jd,
            research_bundle=bundle,
            user=user,
            retrieved_entries=retrieved,
        )

    lq = await generator()
    lq = await _audit_and_ship(lq, bundle, style_profile, company_name, generator, session.session_id)
    return lq


async def handle_salary_advice(
    session: Session,
    user: UserProfile,
    storage: Storage,
) -> SalaryRecommendation:
    from .sub_agents import salary_strategist

    bundle = await _load_session_bundle(session, storage)
    style_profile = await _get_style_profile(user, storage) or _fallback_style()
    ctx = await compute_job_search_context(user, storage)

    if not bundle:
        raise ValueError("No research bundle — forward a job first")

    return await salary_strategist.generate(
        jd=bundle.extracted_jd,
        research_bundle=bundle,
        user=user,
        context=ctx,
        style_profile=style_profile,
    )


async def handle_full_prep(
    session: Session,
    user: UserProfile,
    storage: Storage,
    star_polishes: Optional[list[STARPolish]] = None,
) -> Pack:
    """Parallel fan-out of all 4 Phase 4 generators."""
    cv_task = asyncio.create_task(
        handle_draft_cv(session, user, storage, star_polishes)
    )
    cl_task = asyncio.create_task(
        handle_draft_cover_letter(session, user, storage, star_polishes)
    )
    lq_task = asyncio.create_task(
        handle_predict_questions(session, user, storage)
    )
    sal_task = asyncio.create_task(
        handle_salary_advice(session, user, storage)
    )

    results = await asyncio.gather(cv_task, cl_task, lq_task, sal_task, return_exceptions=True)

    cv_out = cl_out = lq_out = sal_out = None
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            log.error("full_prep sub-task %d failed: %s", i, result)
        else:
            if i == 0:
                cv_out, _, _ = result
            elif i == 1:
                cl_out, _, _ = result
            elif i == 2:
                lq_out = result
            elif i == 3:
                sal_out = result

    return Pack(
        session_id=session.session_id,
        cv=cv_out,
        cover_letter=cl_out,
        likely_questions=lq_out,
        salary=sal_out,
    )


async def handle_draft_reply(
    incoming_message: str,
    user_intent: str,
    user: UserProfile,
    storage: Storage,
    session_id: Optional[str] = None,
) -> DraftReplyOutput:
    from .sub_agents import draft_reply

    style_profile = await _get_style_profile(user, storage) or _fallback_style()
    relevant = await storage.retrieve_relevant_entries(
        user_id=user.user_id, query=incoming_message[:200], k=5
    )

    return await draft_reply.generate(
        incoming_message=incoming_message,
        user_intent_hint=user_intent,
        user=user,
        style_profile=style_profile,
        relevant_entries=relevant,
    )


# ---------------------------------------------------------------------------
# Job search context
# ---------------------------------------------------------------------------


async def compute_job_search_context(
    user: UserProfile, storage: Storage
) -> JobSearchContext:
    today = date.today()
    search_duration = max(
        1, (today - user.search_started_date).days // 30
    )

    months_until_expiry: Optional[int] = None
    if user.visa_status:
        days_left = (user.visa_status.expiry_date - today).days
        months_until_expiry = max(0, days_left // 30)

    recent_sessions = await storage.get_recent_sessions(user.user_id, limit=30)
    apps_30d = sum(
        1 for s in recent_sessions
        if s.intent == "forward_job"
        and (today - s.created_at.date()).days <= 30
    )
    rejections = sum(
        1 for s in recent_sessions
        if s.verdict and (
            (isinstance(s.verdict, dict) and s.verdict.get("decision") == "NO_GO")
            or (hasattr(s.verdict, "decision") and s.verdict.decision == "NO_GO")
        )
    )

    if months_until_expiry is not None and months_until_expiry < 3:
        urgency = "CRITICAL"
    elif months_until_expiry is not None and months_until_expiry < 6:
        urgency = "HIGH"
    elif user.current_employment == "UNEMPLOYED" and search_duration >= 3:
        urgency = "HIGH"
    elif user.current_employment == "UNEMPLOYED":
        urgency = "MEDIUM"
    elif rejections >= 5:
        urgency = "MEDIUM"
    else:
        urgency = "LOW"

    return JobSearchContext(
        user_id=user.user_id,
        urgency_level=urgency,
        recent_rejections_count=rejections,
        months_until_visa_expiry=months_until_expiry,
        applications_in_last_30_days=apps_30d,
        search_duration_months=search_duration,
    )


# ---------------------------------------------------------------------------
# Fallback style (when no samples collected yet)
# ---------------------------------------------------------------------------


def _fallback_style() -> WritingStyleProfile:
    now = datetime.utcnow()
    return WritingStyleProfile(
        profile_id="fallback",
        user_id="unknown",
        tone="professional and clear",
        sentence_length_pref="medium",
        formality_level=6,
        hedging_tendency="moderate",
        signature_patterns=[],
        avoided_patterns=[],
        examples=[],
        source_sample_ids=[],
        sample_count=0,
        low_confidence_reason="no writing samples collected",
        created_at=now,
        updated_at=now,
    )
