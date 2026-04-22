"""Top-level pipeline coordination.

Implements all intent handlers. Bot handlers call into this module.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from .config import settings
from .schemas import (
    CareerEntry,
    Citation,
    ContentShieldVerdict,
    CoverLetterOutput,
    CVOutput,
    DraftReplyOutput,
    ExtractedJobDescription,
    HardBlocker,
    JobSearchContext,
    LikelyQuestionsOutput,
    MotivationFitReport,
    Pack,
    ReasoningPoint,
    ResearchBundle,
    SalaryRecommendation,
    Session,
    STARPolish,
    StretchConcern,
    UserProfile,
    Verdict,
    WritingStyleProfile,
)
from .storage import Storage
from .validators.citations import build_context
from .validators.content_shield import (
    ContentIntegrityRejected,
    shield as shield_content,
)

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

    # red_flags depends on reviews; we share a single coroutine via a Future
    # so reviews still runs concurrently with the rest of the fan-out but
    # red_flags can await its actual result instead of being given [].
    reviews_future: asyncio.Future = asyncio.get_running_loop().create_future()

    async def run_reviews():
        try:
            result = await rev_agent.fetch(
                company_name=company_research.company_name,
            )
            await mark("reviews")
            if not reviews_future.done():
                reviews_future.set_result(result)
            return result
        except Exception as exc:
            log.warning("reviews failed: %s", exc)
            await mark("reviews")
            if not reviews_future.done():
                reviews_future.set_result([])
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
                job_url=job_url,
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
            # Wait for reviews to complete (or fail to []) before scoring.
            reviews_for_flags = await reviews_future
            result = await rf_agent.detect(
                company_research=company_research,
                companies_house=ch_snapshot,
                reviews=reviews_for_flags,
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
        bundle_completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    await storage.save_phase1_output(session.session_id, bundle)

    # ── Phase 2: Verdict ───────────────────────────────────────────────────
    log.info("Phase 2: verdict")

    # CLAUDE.md Rule 10: every piece of scraped content must go through
    # the Content Shield before reaching a high-stakes agent. The verdict
    # agent is the highest-stakes call in the pipeline — Tier 2 runs when
    # Tier 1 flags anything. A REJECT short-circuits to a minimal fallback
    # verdict instead of shipping an agent-steered decision.
    shielded_bundle, shield_verdict = await _shield_bundle(bundle, "verdict")
    if shield_verdict and shield_verdict.recommended_action == "REJECT":
        log.warning(
            "Content shield rejected scraped content for session %s: %s",
            session.session_id,
            shield_verdict.reasoning,
        )
        fallback = _build_shielded_fallback_verdict(bundle, shield_verdict)
        await storage.save_verdict(session.session_id, fallback)
        return bundle, fallback

    retrieved = await storage.retrieve_relevant_entries(
        user_id=user.user_id,
        query=f"{jd.role_title} {' '.join(jd.required_skills[:5])}",
        k=8,
    )

    verdict = await verdict_agent.generate(
        research_bundle=shielded_bundle,
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


# ---------------------------------------------------------------------------
# Content Shield — bundle-wide wrapper (CLAUDE.md Rule 10, AGENTS.md §18)
# ---------------------------------------------------------------------------


_CLASSIFICATION_RANK = {"SAFE": 0, "SUSPICIOUS": 1, "MALICIOUS": 2}


def _worse(
    a: Optional[ContentShieldVerdict], b: Optional[ContentShieldVerdict]
) -> Optional[ContentShieldVerdict]:
    if a is None:
        return b
    if b is None:
        return a
    return (
        a
        if _CLASSIFICATION_RANK[a.classification]
        >= _CLASSIFICATION_RANK[b.classification]
        else b
    )


async def _shield_bundle(
    bundle: ResearchBundle, downstream_agent: str
) -> tuple[ResearchBundle, Optional[ContentShieldVerdict]]:
    """Shield every untrusted string field in the research bundle before
    it's serialised into a downstream agent prompt.

    Untrusted fields:
      - extracted_jd.jd_text_full
      - company_research.scraped_pages[].text
      - company_research.values[].snippet (verbatim scrape)

    Tier 1 always runs; Tier 2 runs only when Tier 1 flagged AND the
    `downstream_agent` is high-stakes (see content_shield.HIGH_STAKES_AGENTS).
    The returned bundle holds the cleaned strings; callers should pass it
    to both `build_context` and the agent so citation resolution stays
    consistent with what the model actually saw.
    """
    worst: Optional[ContentShieldVerdict] = None

    cleaned_jd_text, jd_v = await shield_content(
        content=bundle.extracted_jd.jd_text_full,
        source_type="scraped_jd",
        downstream_agent=downstream_agent,
    )
    worst = _worse(worst, jd_v)

    cleaned_pages = []
    for p in bundle.company_research.scraped_pages:
        cleaned_text, page_v = await shield_content(
            content=p.text,
            source_type="scraped_company_page",
            downstream_agent=downstream_agent,
        )
        cleaned_pages.append(p.model_copy(update={"text": cleaned_text}))
        worst = _worse(worst, page_v)

    cleaned_claims = []
    for claim in bundle.company_research.culture_claims:
        cleaned_snippet, val_v = await shield_content(
            content=claim.verbatim_snippet,
            source_type="scraped_company_page",
            downstream_agent=downstream_agent,
        )
        cleaned_claims.append(
            claim.model_copy(update={"verbatim_snippet": cleaned_snippet})
        )
        worst = _worse(worst, val_v)

    new_bundle = bundle.model_copy(
        update={
            "extracted_jd": bundle.extracted_jd.model_copy(
                update={"jd_text_full": cleaned_jd_text}
            ),
            "company_research": bundle.company_research.model_copy(
                update={
                    "scraped_pages": cleaned_pages,
                    "culture_claims": cleaned_claims,
                }
            ),
        }
    )
    return new_bundle, worst


def _build_shielded_fallback_verdict(
    bundle: ResearchBundle, verdict: ContentShieldVerdict
) -> Verdict:
    """Minimal NO_GO verdict produced when the Content Shield rejects the
    research bundle. AGENTS.md §18 specifies "minimal verdict with
    'content integrity concern' as a stretch concern" — modelled here as
    a NO_GO with a single stretch concern + one reasoning point.
    """
    role = bundle.extracted_jd.role_title or "this role"
    citation = Citation(
        kind="gov_data",
        data_field="content_shield.recommended_action",
        data_value=verdict.recommended_action,
    )
    return Verdict(
        decision="NO_GO",
        confidence_pct=40,
        headline="Don't apply — page content failed integrity check.",
        reasoning=[
            ReasoningPoint(
                claim=(
                    f"Could not safely produce a verdict for {role} — the "
                    "scraped page tripped the content shield."
                ),
                supporting_evidence=verdict.reasoning,
                citation=citation,
            )
        ],
        hard_blockers=[],
        stretch_concerns=[
            StretchConcern(
                type="CONTENT_INTEGRITY_CONCERN",
                detail=(
                    "Tier 2 classifier returned "
                    f"{verdict.classification} / {verdict.recommended_action}. "
                    "The job URL may be compromised or the page was modified."
                ),
                citations=[citation],
            )
        ],
        motivation_fit=MotivationFitReport(
            motivation_evaluations=[],
            deal_breaker_evaluations=[],
            good_role_signal_evaluations=[],
        ),
    )


def _apply_rewrites_to_strings(obj, rewrites: list[tuple[str, str]]):
    """Walk a nested JSON-ish structure, applying (find, replace) substitutions
    to every string leaf. Model is revalidated after.

    This replaces the prior `json.dumps → str.replace → json.loads` approach,
    which corrupted payloads whenever an offending_substring contained
    quotes, backslashes, or other JSON-significant bytes.
    """
    if isinstance(obj, str):
        out = obj
        for find, replace in rewrites:
            if find and find in out:
                out = out.replace(find, replace, 1)
        return out
    if isinstance(obj, list):
        return [_apply_rewrites_to_strings(x, rewrites) for x in obj]
    if isinstance(obj, dict):
        return {k: _apply_rewrites_to_strings(v, rewrites) for k, v in obj.items()}
    return obj


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

    log.info("Self-audit: %d flags — applying rewrites", len(audit.flags))
    rewrites = [
        (f.offending_substring, f.proposed_rewrite)
        for f in audit.flags
        if f.offending_substring and f.proposed_rewrite
    ]
    if not rewrites:
        return generated
    try:
        patched_dict = _apply_rewrites_to_strings(
            generated.model_dump(mode="json"), rewrites
        )
        return generated.__class__.model_validate(patched_dict)
    except Exception as exc:
        log.warning("Rewrite application failed: %s — shipping original", exc)
        return generated


def _output_dir(session_id: str) -> Path:
    out_dir = settings.generated_dir / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


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
    from .renderers import render_cv_docx, render_cv_pdf

    bundle = await _load_session_bundle(session, storage)
    if bundle is None:
        raise ValueError(
            "No research bundle on session — forward a job URL before requesting a CV."
        )
    # CLAUDE.md Rule 10: every Phase 4 generator is a high-stakes agent.
    # Shield the bundle before build_context so citation resolution uses
    # the same (redacted) text the model sees.
    bundle, shield_verdict = await _shield_bundle(bundle, "cv_tailor")
    if shield_verdict and shield_verdict.recommended_action == "REJECT":
        raise ContentIntegrityRejected(shield_verdict, "scraped_jd")

    style_profile = await _get_style_profile(user, storage) or _fallback_style()

    jd = bundle.extracted_jd
    query = f"{jd.role_title} {' '.join((jd.required_skills or [])[:5])}"
    retrieved = await storage.retrieve_relevant_entries(
        user_id=user.user_id, query=query, k=12
    )

    company_name = bundle.company_research.company_name

    citation_ctx = await build_context(
        research_bundle=bundle,
        user_id=user.user_id,
        career_entries=retrieved,
    )

    async def generator():
        return await cv_tailor.generate(
            jd=jd,
            research_bundle=bundle,
            user=user,
            retrieved_entries=retrieved,
            style_profile=style_profile,
            star_material=star_polishes,
            citation_ctx=citation_ctx,
        )

    cv = await generator()
    cv = await _audit_and_ship(
        cv, bundle, style_profile, company_name, generator, session.session_id
    )

    out_dir = _output_dir(session.session_id)
    docx_path = render_cv_docx(cv, out_dir, company=company_name)
    pdf_path = render_cv_pdf(cv, out_dir, company=company_name)

    return cv, docx_path, pdf_path


async def handle_draft_cover_letter(
    session: Session,
    user: UserProfile,
    storage: Storage,
    star_polishes: Optional[list[STARPolish]] = None,
) -> tuple[CoverLetterOutput, Path, Path]:
    from .sub_agents import cover_letter
    from .renderers import render_cover_letter_docx, render_cover_letter_pdf

    bundle = await _load_session_bundle(session, storage)
    if bundle is None:
        raise ValueError(
            "No research bundle on session — forward a job URL before requesting a cover letter."
        )
    bundle, shield_verdict = await _shield_bundle(bundle, "cover_letter")
    if shield_verdict and shield_verdict.recommended_action == "REJECT":
        raise ContentIntegrityRejected(shield_verdict, "scraped_jd")

    style_profile = await _get_style_profile(user, storage) or _fallback_style()

    jd = bundle.extracted_jd
    query = f"{jd.role_title} cover letter"
    retrieved = await storage.retrieve_relevant_entries(
        user_id=user.user_id, query=query, k=10
    )

    company_name = bundle.company_research.company_name

    citation_ctx = await build_context(
        research_bundle=bundle,
        user_id=user.user_id,
        career_entries=retrieved,
    )

    async def generator():
        return await cover_letter.generate(
            jd=jd,
            research_bundle=bundle,
            user=user,
            retrieved_entries=retrieved,
            style_profile=style_profile,
            star_material=star_polishes,
            citation_ctx=citation_ctx,
        )

    cl = await generator()
    cl = await _audit_and_ship(
        cl, bundle, style_profile, company_name, generator, session.session_id
    )

    out_dir = _output_dir(session.session_id)
    docx_path = render_cover_letter_docx(cl, out_dir, sender_name=user.name)
    pdf_path = render_cover_letter_pdf(cl, out_dir, sender_name=user.name)

    return cl, docx_path, pdf_path


async def handle_predict_questions(
    session: Session,
    user: UserProfile,
    storage: Storage,
) -> LikelyQuestionsOutput:
    from .sub_agents import likely_questions

    bundle = await _load_session_bundle(session, storage)
    if bundle is None:
        raise ValueError(
            "No research bundle on session — forward a job URL before predicting questions."
        )
    bundle, shield_verdict = await _shield_bundle(bundle, "likely_questions")
    if shield_verdict and shield_verdict.recommended_action == "REJECT":
        raise ContentIntegrityRejected(shield_verdict, "scraped_jd")

    style_profile = await _get_style_profile(user, storage) or _fallback_style()

    jd = bundle.extracted_jd
    query = f"{jd.role_title} interview"
    retrieved = await storage.retrieve_relevant_entries(
        user_id=user.user_id, query=query, k=10
    )

    company_name = bundle.company_research.company_name

    citation_ctx = await build_context(
        research_bundle=bundle,
        user_id=user.user_id,
        career_entries=retrieved,
    )

    async def generator():
        return await likely_questions.generate(
            jd=jd,
            research_bundle=bundle,
            user=user,
            retrieved_entries=retrieved,
            citation_ctx=citation_ctx,
        )

    lq = await generator()
    lq = await _audit_and_ship(
        lq, bundle, style_profile, company_name, generator, session.session_id
    )
    return lq


async def handle_salary_advice(
    session: Session,
    user: UserProfile,
    storage: Storage,
) -> SalaryRecommendation:
    from .sub_agents import salary_strategist

    bundle = await _load_session_bundle(session, storage)
    if not bundle:
        raise ValueError("No research bundle — forward a job first")

    bundle, shield_verdict = await _shield_bundle(bundle, "salary_strategist")
    if shield_verdict and shield_verdict.recommended_action == "REJECT":
        raise ContentIntegrityRejected(shield_verdict, "scraped_jd")

    style_profile = await _get_style_profile(user, storage) or _fallback_style()
    ctx = await compute_job_search_context(user, storage)

    citation_ctx = await build_context(
        research_bundle=bundle,
        user_id=user.user_id,
        career_entries=[],
    )

    return await salary_strategist.generate(
        jd=bundle.extracted_jd,
        research_bundle=bundle,
        user=user,
        context=ctx,
        style_profile=style_profile,
        citation_ctx=citation_ctx,
    )


async def handle_full_prep(
    session: Session,
    user: UserProfile,
    storage: Storage,
    star_polishes: Optional[list[STARPolish]] = None,
) -> tuple[Pack, dict[str, Path]]:
    """Parallel fan-out of all 4 Phase 4 generators.

    Returns the Pack plus a mapping of file kinds to rendered paths so the
    bot surface can attach the .docx/.pdf deliverables (CLAUDE.md Rule 9).
    """
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

    results = await asyncio.gather(
        cv_task, cl_task, lq_task, sal_task, return_exceptions=True
    )

    cv_out = cl_out = lq_out = sal_out = None
    files: dict[str, Path] = {}
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            log.error("full_prep sub-task %d failed: %s", i, result)
            continue
        if i == 0:
            cv_out, cv_docx, cv_pdf = result
            files["cv_docx"] = cv_docx
            files["cv_pdf"] = cv_pdf
        elif i == 1:
            cl_out, cl_docx, cl_pdf = result
            files["cover_letter_docx"] = cl_docx
            files["cover_letter_pdf"] = cl_pdf
        elif i == 2:
            lq_out = result
        elif i == 3:
            sal_out = result

    pack = Pack(
        session_id=session.session_id,
        cv=cv_out,
        cover_letter=cl_out,
        likely_questions=lq_out,
        salary=sal_out,
    )
    return pack, files


async def handle_draft_reply(
    incoming_message: str,
    user_intent: str,
    user: UserProfile,
    storage: Storage,
    session_id: Optional[str] = None,
) -> DraftReplyOutput:
    from .sub_agents import draft_reply

    # CLAUDE.md Rule 10: pasted recruiter email is the primary injection
    # vector — shield before the high-stakes generator.
    cleaned_msg, shield_verdict = await shield_content(
        content=incoming_message,
        source_type="recruiter_email",
        downstream_agent="draft_reply",
    )
    if shield_verdict and shield_verdict.recommended_action == "REJECT":
        raise ContentIntegrityRejected(shield_verdict, "recruiter_email")

    style_profile = await _get_style_profile(user, storage) or _fallback_style()
    relevant = await storage.retrieve_relevant_entries(
        user_id=user.user_id, query=cleaned_msg[:200], k=5
    )

    return await draft_reply.generate(
        incoming_message=cleaned_msg,
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
    now = datetime.now(timezone.utc).replace(tzinfo=None)
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
