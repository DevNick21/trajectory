"""Top-level pipeline coordination.

Implements all intent handlers. Bot handlers call into this module.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from .config import settings
from .progress import NoOpEmitter, ProgressEmitter
from .schemas import (
    CareerEntry,
    Citation,
    ContentShieldVerdict,
    CoverLetterOutput,
    CVOutput,
    DraftReplyOutput,
    ExtractedJobDescription,
    GhostJobAssessment,
    GhostJobJDScore,
    HardBlocker,
    JobSearchContext,
    LikelyQuestionsOutput,
    MotivationFitReport,
    Pack,
    ReasoningPoint,
    RedFlagsReport,
    ResearchBundle,
    SalaryRecommendation,
    Session,
    STARPolish,
    StretchConcern,
    UserProfile,
    Verdict,
    WritingStyleProfile,
    is_blocking_verdict,
    is_positive_verdict,
)
from .storage import STAR_BOOST_KINDS, Storage
from .validators.citations import build_context
from .validators.content_shield import (
    ContentIntegrityRejected,
    shield as shield_content,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase 1 — Research + Verdict
# ---------------------------------------------------------------------------


PHASE_1_AGENTS: list[str] = [
    # Phase 1A (serial)
    "phase_1_jd_extractor",
    "phase_1_company_scraper_summariser",
    # Phase 0 — triage (runs after JD + company scrape, before 1C)
    "phase_0_triage",
    # Phase 1C (parallel — ordered by typical completion latency so the
    # visual ticking on the surface matches the order checkmarks
    # actually appear: parquet lookups fastest, then the scraper, then
    # the Opus xhigh agents, with red_flags last because it waits on
    # reviews).
    "companies_house",
    "sponsor_register",
    "soc_check",
    "gazette_check",
    "reviews",
    "phase_1_ghost_job_jd_scorer",
    "phase_1_red_flags",
]


async def handle_forward_job(
    job_url: str,
    user: UserProfile,
    session: Session,
    storage: Storage,
    emitter: Optional[ProgressEmitter] = None,
) -> tuple[ResearchBundle, Verdict]:
    """Run Phase 1 (8 sub-agents) + Phase 2 (verdict). Returns bundle + verdict.

    `emitter` receives transport-agnostic progress events
    (`{"type": "agent_complete", "agent": <name>}`). When omitted,
    a NoOpEmitter is used — safe default for CLI runs and tests. The
    Telegram bot wraps a `PhaseOneProgressStreamer` in a
    `TelegramEmitter`; the FastAPI surface (Wave 4) wires an
    `SSEEmitter` to an asyncio.Queue. See MIGRATION_PLAN.md ADR-002.
    """
    from .sub_agents import (
        company_scraper,
        companies_house as ch_agent,
        red_flags as rf_agent,
        ghost_job_detector,
        gazette_check,
        sponsor_register as sr_agent,
        soc_check as soc_agent,
        verdict as verdict_agent,
    )

    if emitter is None:
        emitter = NoOpEmitter()

    async def mark(name: str) -> None:
        await emitter.emit({"type": "agent_complete", "agent": name})

    # ── Phase 1A: company scraper (JD + company research, serial) ─────────
    log.info("Phase 1A: company_scraper for %s", job_url)
    # Fire the JD-extractor tick the moment _extract_jd returns inside
    # company_scraper, BEFORE the company-page scrape + summariser run.
    # Without this, both ticks pop together at the end of the full
    # ~30-50s block and the UI sits at `○` the whole time.
    company_research, jd = await company_scraper.run(
        job_url=job_url,
        session_id=session.session_id,
        on_jd_extracted=lambda: mark("phase_1_jd_extractor"),
    )
    await mark("phase_1_company_scraper_summariser")

    # Cache scraped pages from company_research
    for page in company_research.scraped_pages:
        await storage.cache_scraped_page(page.url, page.text, page.fetched_at)

    # ── Phase 0: Triage (architecture gap #4) ──────────────────────────────
    # A Haiku call (~$0.02) that gates whether the full $1-2 Phase 1
    # pipeline runs at all. DEFINITE_PASS skips the pipeline entirely;
    # EXPLORATORY runs the verdict with medium effort; SERIOUS gets the
    # full Opus verdict. Single biggest cost-leverage move.
    triage_result = None
    try:
        from .sub_agents.triage import classify as triage_classify
        triage_result = await triage_classify(
            jd=jd,
            user=user,
            retrieved_entries=None,  # triage is pre-retrieval by design
        )
        await mark("phase_0_triage")
        log.info(
            "Phase 0 triage: %s — %s",
            triage_result.classification,
            triage_result.reasoning_brief,
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("Triage failed (non-fatal, defaults to SERIOUS): %s", exc)

    if triage_result and triage_result.classification == "DEFINITE_PASS":
        log.info(
            "Triage DEFINITE_PASS — skipping Phase 1 pipeline for %s: %s",
            job_url,
            triage_result.reasoning_brief,
        )
        verdict = Verdict(
            decision="PASS",
            confidence_pct=95,
            entropy_norm=0.0,
            headline="Skip this one — " + triage_result.reasoning_brief[:80],
            reasoning=[
                ReasoningPoint(
                    claim=triage_result.reasoning_brief,
                    citation=Citation(
                        kind="gov_data",
                        data_field="triage_classification",
                        data_value="DEFINITE_PASS",
                    ),
                )
            ],
            hard_blockers=[],
            stretch_concerns=[],
            motivation_fit=MotivationFitReport(
                motivation_evaluations=[],
                deal_breaker_evaluations=[],
                good_role_signal_evaluations=[],
            ),
        )
        # Build minimal bundle so the session has the JD and company name
        minimal_bundle = ResearchBundle(
            session_id=session.session_id,
            extracted_jd=jd,
            company_research=company_research,
            ghost_job=GhostJobAssessment(
                probability="LIKELY_REAL",
                signals=[],
                confidence="LOW",
                raw_jd_score=GhostJobJDScore(
                    named_hiring_manager=0.0,
                    specific_duty_bullets=0.0,
                    specific_tech_stack=0.0,
                    specific_team_context=0.0,
                    specific_success_metrics=0.0,
                    specificity_score=2.5,
                    specificity_signals=[],
                    vagueness_signals=[],
                ),
            ),
            red_flags=RedFlagsReport(flags=[], checked=False),
            bundle_completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        await storage.save_phase1_output(session.session_id, minimal_bundle)
        await storage.save_verdict(session.session_id, verdict)
        return minimal_bundle, verdict

    # ── Phase 1A.5: unified company identity resolution ────────────────────
    # One canonical name + CRN per real-world employer, shared by every
    # downstream lookup (companies_house, sponsor_register, and the
    # front-page sponsor-search / visa-eligibility tools).
    #
    # Pipeline with the five hardening layers:
    #   L1 (alias expansion) — handled inside resolve_company_identity.
    #   L2 (domain seeds)    — pass company_research.company_domain.
    #   L3 (footer CRN)      — extract here from scraped_pages; if found,
    #                          pass as crn_hint so resolve_company_identity
    #                          short-circuits to the direct profile fetch.
    #   L4 (shell penalty)   — applied inside _score_ch_hits.
    #   L5 (multi-token block) — applied in local_ch_index.search_by_name.
    company_identity = None
    try:
        from .entity_resolution import resolve_company_identity
        from .entity_resolution.footer_extractor import extract_hints
        footer_hints = extract_hints(company_research.scraped_pages)
        extra_aliases = (
            [footer_hints.legal_name] if footer_hints.legal_name else None
        )
        if footer_hints.crn:
            log.info(
                "Footer CRN found: %s (legal_name=%r) — using as crn_hint",
                footer_hints.crn, footer_hints.legal_name,
            )
        company_identity = await resolve_company_identity(
            company_research.company_name,
            domain=company_research.company_domain,
            crn_hint=footer_hints.crn,
            additional_aliases=extra_aliases,
        )
        log.info(
            "company identity: id=%s crn=%s conf=%.2f via=%s",
            company_identity.identity_id,
            company_identity.crn,
            company_identity.confidence,
            company_identity.trace.chosen_via if company_identity.trace else "?",
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("resolve_company_identity failed: %s", exc)

    # ── Phase 1B: companies house (fast, needed by ghost detector) ─────────
    log.info("Phase 1B: companies_house")
    ch_snapshot = None
    try:
        ch_kwargs = {"company_name": company_research.company_name}
        if company_identity:
            if company_identity.crn:
                ch_kwargs["crn"] = company_identity.crn
            if company_identity.aliases:
                ch_kwargs["aliases"] = company_identity.aliases
        ch_snapshot = await ch_agent.lookup(**ch_kwargs)
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

    timeout = settings.phase1_agent_timeout_s

    async def run_reviews():
        # Managed Agents reviews_investigator is the only path
        # (ASKPICKY.md §10 cut the legacy jobspy fallback). Failures
        # return [] — reviews are signal enrichment, not a hard blocker.
        try:
            from .llm import call_in_session
            from .schemas import ReviewExcerpt
            managed_out = await asyncio.wait_for(
                call_in_session(
                    "reviews_investigator",
                    company_name=company_research.company_name,
                    company_domain=company_research.company_domain,
                    session_id=session.session_id,
                ),
                timeout=max(timeout * 3, 120),  # MA sessions take longer
            )
            excerpts = [
                ReviewExcerpt(
                    source=ex.source,
                    rating=ex.rating,
                    title=ex.title,
                    text=ex.text,
                    url=ex.url,
                )
                for ex in managed_out.excerpts
            ]
            log.info(
                "reviews_investigator: %d excerpt(s) for %s",
                len(excerpts), company_research.company_name,
            )
            await mark("reviews")
            if not reviews_future.done():
                reviews_future.set_result(excerpts)
            return excerpts
        except (Exception, asyncio.TimeoutError) as exc:
            timed_out = isinstance(exc, asyncio.TimeoutError)
            log.warning(
                "reviews_investigator failed (timed_out=%s): %s",
                timed_out, exc,
            )
            await mark("reviews")
            if not reviews_future.done():
                reviews_future.set_result([])
            return []

    async def run_gazette():
        """The Gazette insolvency-notice check. Hard blocker on any
        active winding-up petition / administrator appointment /
        resolution to wind up. Empty list when the company is fine,
        which is the common case."""
        canonical = None
        if company_identity is not None:
            canonical = getattr(company_identity, "canonical_name", None)
        crn = None
        if company_identity is not None:
            crn = getattr(company_identity, "crn", None)
        try:
            result = await asyncio.wait_for(
                gazette_check.check(
                    company_name=company_research.company_name,
                    canonical_name=canonical,
                    crn=crn,
                ),
                timeout=timeout,
            )
            await mark("gazette_check")
            return result
        except (Exception, asyncio.TimeoutError) as exc:
            timed_out = isinstance(exc, asyncio.TimeoutError)
            log.warning("gazette_check failed (timed_out=%s): %s", timed_out, exc)
            await mark("gazette_check")
            return []

    async def run_sponsor():
        if user.user_type != "visa_holder":
            await mark("sponsor_register")
            return None
        try:
            result = await asyncio.wait_for(
                sr_agent.lookup(
                    company_name=company_research.company_name,
                    identity=company_identity,
                ),
                timeout=timeout,
            )
            await mark("sponsor_register")
            return result
        except (Exception, asyncio.TimeoutError) as exc:
            timed_out = isinstance(exc, asyncio.TimeoutError)
            log.warning(
                "sponsor_register failed (timed_out=%s): %s", timed_out, exc
            )
            await mark("sponsor_register")
            from .schemas import SponsorStatus
            return SponsorStatus(
                status="UNKNOWN",
                source_status="UNREACHABLE",
            )

    async def run_soc():
        if user.user_type != "visa_holder":
            await mark("soc_check")
            return None
        try:
            result = await asyncio.wait_for(
                soc_agent.verify(jd=jd, user=user),
                timeout=timeout,
            )
            await mark("soc_check")
            return result
        except (Exception, asyncio.TimeoutError) as exc:
            timed_out = isinstance(exc, asyncio.TimeoutError)
            log.warning("soc_check failed (timed_out=%s): %s", timed_out, exc)
            await mark("soc_check")
            from .schemas import SocCheckResult
            return SocCheckResult(
                soc_code=jd.soc_code_guess or "unknown",
                soc_title="",
                on_appendix_skilled_occupations=False,
                below_threshold=False,
                source_status="UNREACHABLE",
            )

    async def run_ghost():
        try:
            result = await asyncio.wait_for(
                ghost_job_detector.score(
                    jd=jd,
                    company_research=company_research,
                    companies_house=ch_snapshot,
                    job_url=job_url,
                    session_id=session.session_id,
                ),
                timeout=timeout,
            )
            await mark("phase_1_ghost_job_jd_scorer")
            return result
        except (Exception, asyncio.TimeoutError) as exc:
            # Match the sibling Phase 1C pattern (run_red_flags, run_soc):
            # log + mark + return a conservative fallback rather than
            # raising, since `asyncio.gather(..., return_exceptions=False)`
            # below would otherwise abort the entire verdict on a single
            # detector failure. LIKELY_REAL + LOW confidence is the
            # least-confidently-bad default — the verdict will still
            # surface other hard blockers but won't auto-flip to NO_GO
            # on ghost-job grounds when we have no real signal.
            timed_out = isinstance(exc, asyncio.TimeoutError)
            log.warning(
                "ghost_job_detector failed (timed_out=%s): %s", timed_out, exc
            )
            await mark("phase_1_ghost_job_jd_scorer")
            from .schemas import GhostJobAssessment, GhostJobJDScore
            return GhostJobAssessment(
                probability="LIKELY_REAL",
                signals=[],
                confidence="LOW",
                raw_jd_score=GhostJobJDScore(
                    named_hiring_manager=0.0,
                    specific_duty_bullets=0.0,
                    specific_tech_stack=0.0,
                    specific_team_context=0.0,
                    specific_success_metrics=0.0,
                    specificity_score=0.0,
                    specificity_signals=[],
                    vagueness_signals=["ghost_detector_unavailable"],
                ),
                age_days=None,
            )

    async def run_red_flags():
        try:
            # Wait for reviews to complete (or fail to []) before scoring.
            reviews_for_flags = await reviews_future
            result = await asyncio.wait_for(
                rf_agent.detect(
                    company_research=company_research,
                    companies_house=ch_snapshot,
                    reviews=reviews_for_flags,
                    session_id=session.session_id,
                ),
                timeout=timeout,
            )
            await mark("phase_1_red_flags")
            return result
        except (Exception, asyncio.TimeoutError) as exc:
            timed_out = isinstance(exc, asyncio.TimeoutError)
            log.warning("red_flags failed (timed_out=%s): %s", timed_out, exc)
            await mark("phase_1_red_flags")
            from .schemas import RedFlagsReport
            return RedFlagsReport(flags=[], checked=True)

    (
        review_excerpts,
        gazette_signals,
        sponsor_status,
        soc_result,
        ghost_assessment,
        red_flags_report,
    ) = await asyncio.gather(
        run_reviews(),
        run_gazette(),
        run_sponsor(),
        run_soc(),
        run_ghost(),
        run_red_flags(),
        return_exceptions=False,
    )

    # Architecture gap #2 — parent/subsidiary CRN walk. When the JD's
    # company is a subsidiary that's NOT_LISTED on the Sponsor Register
    # but the parent IS, re-lookup against each corporate PSC parent
    # name and surface matches as alternative_matches with
    # match_path=LOOKS_LIKE_SUB_ENTITY. Skipped when sponsor lookup
    # already found a match or no CH parents exist.
    sponsor_status = await _walk_parent_sponsors(
        sponsor_status=sponsor_status,
        ch_snapshot=ch_snapshot,
        sr_agent=sr_agent,
    )

    # Emitter flush is the caller's responsibility now (Wave 1 ADR-002).
    # bot/handlers.py calls emitter.close() → streamer.flush() on the
    # Telegram path; api/routes/sessions.py closes the SSEEmitter in
    # its `finally` block on the web path.

    bundle = ResearchBundle(
        session_id=session.session_id,
        extracted_jd=jd,
        company_research=company_research,
        company_identity=(
            company_identity.model_dump(mode="json") if company_identity else None
        ),
        companies_house=ch_snapshot,
        sponsor_status=sponsor_status,
        soc_check=soc_result,
        ghost_job=ghost_assessment,
        # Salary signals dropped from Phase 1 fan-out 2026-05-22.
        # `salary_strategist` (on-demand intent) still computes
        # live ASHE-anchored advice when the user asks.
        salary_signals=None,
        red_flags=red_flags_report,
        gazette_signals=gazette_signals,
        bundle_completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    # PROCESS Entry 45 — find-or-create the persistent Job entity. Same
    # role at same company across multiple URL forwards = one job_id.
    # Stamped on the Session so the bot can locate "that Acme role"
    # later by company + title rather than session-recency.
    try:
        from .storage import update_session, upsert_job
        job_id = await upsert_job(
            user_id=user.user_id,
            role_title=jd.role_title,
            company_name=company_research.company_name,
            company_domain=company_research.company_domain,
            last_seen_url=job_url,
        )
        session.job_id = job_id
        await update_session(session)  # refresh row with job_id
    except Exception as exc:
        log.warning("Job entity upsert failed (non-fatal): %s", exc)

    await storage.save_phase1_output(session.session_id, bundle)

    # ── Phase 2: Verdict ───────────────────────────────────────────────────
    log.info("Phase 2: verdict")

    # Quality gate — deterministic pre-verdict pass (runs in <1ms, no LLM).
    # Assesses which Phase 1 signals are reliable and which should be
    # downgraded to advisory. The verdict only reasons about what the gate
    # says is reliable. Same pattern as social media firehose filters.
    quality_gate_result = None
    try:
        from .quality_gate import assess as assess_quality

        quality_gate_result = assess_quality(bundle, user)
        log.info(
            "Quality gate: %d gated, %d upgraded, %d notes",
            len(quality_gate_result.gated),
            len(quality_gate_result.upgrades),
            len(quality_gate_result.notes),
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("Quality gate failed (non-fatal): %s", exc)

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

    # Architecture gap #3 — outcome-to-verdict calibration. Before the
    # verdict reasons about a company, recall the user's prior application
    # outcomes so the agent can calibrate its confidence. The user who has
    # ignored 5 NO_GOs and succeeded anyway gets a different verdict from
    # the user with zero history.
    prior_outcomes_text: Optional[str] = None
    try:
        from .memory.recall import recall_as_text

        prior_outcomes_text = await recall_as_text(
            user_id=user.user_id,
            kind="application_outcome",
            limit=10,
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("Prior outcome recall failed (non-fatal): %s", exc)

    # Single verdict call. The ensemble path (parallel x2 with conservative
    # merge) was cut in the 2026-05-22 overhaul — voice-incompatible with
    # Picky's confident voice (ASKPICKY.md §10 "Cut entirely"). The deep-
    # research variant survives as the premium "Real-time hiring intent
    # verification" feature (ASKPICKY.md §8).
    verdict = await verdict_agent.generate(
        research_bundle=shielded_bundle,
        user=user,
        retrieved_entries=retrieved,
        session_id=session.session_id,
        prior_outcomes_text=prior_outcomes_text,
        quality_gate=quality_gate_result,
    )

    await storage.save_verdict(session.session_id, verdict)

    # ASKPICKY.md §6 Layer 6 — feed the data network flywheel. Every
    # forward_job that produces a verdict creates a tracker row and
    # schedules the multi-step outcome nudge across the user's
    # available channels. Outcome recording (from any surface) cancels
    # the pending nudges. Best-effort: never fail the forward_job on
    # a notifications glitch.
    try:
        from .notifications import (
            create_application_record,
            schedule_outcome_nudge,
        )
        from .notifications.dispatcher import preferred_channels_for_user

        company_name = bundle.company_research.company_name
        role_title = bundle.extracted_jd.role_title
        await create_application_record(
            user_id=user.user_id,
            session_id=session.session_id,
            company_name=company_name,
            role_title=role_title,
            job_url=session.job_url,
            verdict_decision=verdict.decision,
        )
        channels = preferred_channels_for_user(user)
        await schedule_outcome_nudge(
            user_id=user.user_id,
            session_id=session.session_id,
            company_name=company_name,
            role_title=role_title,
            channels=channels,
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("Failed to wire tracker/nudges for session %s: %s",
                    session.session_id, exc)

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


async def _walk_parent_sponsors(
    *,
    sponsor_status,
    ch_snapshot,
    sr_agent,
):
    """Architecture gap #2 — parent/subsidiary CRN walk.

    When the JD's company is a subsidiary that's NOT_LISTED on the
    Sponsor Register but its corporate PSC parents may be listed,
    re-lookup each parent and append matches to
    `sponsor_status.alternative_matches` with
    match_path=LOOKS_LIKE_SUB_ENTITY.

    Pure additive — never demotes an existing match. Returns the
    (possibly-updated) sponsor_status. No-op when:
      - sponsor already found a primary match (status != NOT_LISTED), OR
      - companies_house didn't return parent_companies, OR
      - all parents are unlisted too.
    """
    from .schemas import SponsorAlternativeMatch

    if sponsor_status is None or ch_snapshot is None:
        return sponsor_status
    if sponsor_status.status != "NOT_LISTED":
        return sponsor_status
    parents = ch_snapshot.parent_companies
    if not parents:
        return sponsor_status

    new_matches: list[SponsorAlternativeMatch] = list(
        sponsor_status.alternative_matches or []
    )
    matched_any = False
    for parent in parents:
        try:
            parent_status = await sr_agent.lookup(parent.name)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "Parent-walk sponsor lookup failed for %r: %s",
                parent.name, exc,
            )
            continue
        if parent_status.status in {"LISTED", "B_RATED", "SUSPENDED"}:
            matched_any = True
            new_matches.append(
                SponsorAlternativeMatch(
                    matched_name=(
                        parent_status.matched_name or parent.name
                    ),
                    rating=parent_status.rating,
                    status=parent_status.status,
                    # Best-confidence sentinel: a parent-walked match
                    # is high-recall but low-direct-relevance. Score
                    # 80 (above the alt-match threshold) so the
                    # verdict prompt's AMBIGUITY TIER picks it up.
                    score=80.0,
                )
            )

    if not matched_any:
        return sponsor_status

    # Demote status to AMBIGUOUS so the verdict prompt's tier override
    # routes NOT_LISTED → stretch concern instead of hard blocker.
    return sponsor_status.model_copy(
        update={
            "status": "AMBIGUOUS",
            "match_path": "LOOKS_LIKE_SUB_ENTITY",
            "alternative_matches": new_matches,
        }
    )


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

    A5: any source whose Tier 1 pass truncated the content is recorded
    in `new_bundle.sources_truncated`. The verdict agent surfaces this
    to the user as a "partial view" caveat and downgrades confidence.
    """
    worst: Optional[ContentShieldVerdict] = None
    truncated_sources: list[str] = []

    jd_result = await shield_content(
        content=bundle.extracted_jd.jd_text_full,
        source_type="scraped_jd",
        downstream_agent=downstream_agent,
    )
    cleaned_jd_text = jd_result.cleaned_text
    worst = _worse(worst, jd_result.verdict)
    if jd_result.truncated:
        truncated_sources.append("extracted_jd")

    cleaned_pages = []
    for idx, p in enumerate(bundle.company_research.scraped_pages):
        page_result = await shield_content(
            content=p.text,
            source_type="scraped_company_page",
            downstream_agent=downstream_agent,
        )
        cleaned_pages.append(p.model_copy(update={"text": page_result.cleaned_text}))
        worst = _worse(worst, page_result.verdict)
        if page_result.truncated:
            truncated_sources.append(f"scraped_page:{idx}:{p.url}")

    cleaned_claims = []
    for claim in bundle.company_research.culture_claims:
        claim_result = await shield_content(
            content=claim.verbatim_snippet,
            source_type="scraped_company_page",
            downstream_agent=downstream_agent,
        )
        cleaned_claims.append(
            claim.model_copy(
                update={"verbatim_snippet": claim_result.cleaned_text}
            )
        )
        worst = _worse(worst, claim_result.verdict)
        # Culture snippets are small by design; truncation here would
        # mean a pathological input, but track it for completeness.
        if claim_result.truncated:
            truncated_sources.append("culture_claim")

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
            "sources_truncated": list(
                dict.fromkeys(list(bundle.sources_truncated) + truncated_sources)
            ),
        }
    )
    return new_bundle, worst


def _build_shielded_fallback_verdict(
    bundle: ResearchBundle, verdict: ContentShieldVerdict
) -> Verdict:
    """Minimal BLOCKED verdict produced when the Content Shield rejects the
    research bundle. AGENTS.md §18 specifies "minimal verdict with
    'content integrity concern' as a stretch concern" — modelled here as
    a BLOCKED with a single stretch concern + one reasoning point.
    """
    role = bundle.extracted_jd.role_title or "this role"
    citation = Citation(
        kind="gov_data",
        data_field="content_shield.recommended_action",
        data_value=verdict.recommended_action,
    )
    return Verdict(
        decision="BLOCKED",
        confidence_pct=40,
        entropy_norm=0.0,
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

    Known limitation: rewrites apply to the FIRST occurrence of
    offending_substring within each string leaf. If the same banned phrase
    appears in both, say, a CV bullet and the cover letter body, only the
    first hit in each field is replaced. In practice the self-audit LLM
    rarely emits >3 flags per generation and duplicate banned phrases are
    uncommon enough that this is a tolerable failure mode; fixing it
    properly requires threading a field-path through AuditFlag and has
    been left out of scope. See PROCESS.md if we revisit.
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
    """Returns (cv, docx_path, pdf_path).

    Anthropic-only agentic FAISS-retrieval path. The multi-provider
    routing and LaTeX-typeset branches were cut in the 2026-05-22
    overhaul (ASKPICKY.md §10).
    """
    from .sub_agents import cv_tailor_agentic as cv_tailor
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

    style_profile = await _get_style_profile(user, storage) or _fallback_style(user.user_id)

    jd = bundle.extracted_jd
    query = f"{jd.role_title} {' '.join((jd.required_skills or [])[:5])}"
    retrieved = await storage.retrieve_relevant_entries(
        user_id=user.user_id, query=query, k=12,
        kind_weights=STAR_BOOST_KINDS,
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

    style_profile = await _get_style_profile(user, storage) or _fallback_style(user.user_id)

    jd = bundle.extracted_jd
    query = f"{jd.role_title} cover letter"
    retrieved = await storage.retrieve_relevant_entries(
        user_id=user.user_id, query=query, k=10,
        kind_weights=STAR_BOOST_KINDS,
    )

    company_name = bundle.company_research.company_name

    # PROCESS Entry 45 — managed cover_letter routing.
    # When the flag is on, dispatch to the live-web-equipped session
    # that re-fetches culture pages targeted to this user's motivations.
    # Falls back to the in-process path on session failure.
    if settings.enable_managed_cover_letter:
        from .llm import call_in_session

        async def generator():
            try:
                return await call_in_session(
                    "cover_letter_managed",
                    jd=jd,
                    research_bundle=bundle,
                    user=user,
                    retrieved_entries=retrieved,
                    style_profile=style_profile,
                    star_material=star_polishes,
                    session_id=session.session_id,
                )
            except Exception as exc:
                log.warning(
                    "cover_letter_managed failed; falling back to in-process: %s",
                    exc,
                )
                return await cover_letter.generate(
                    jd=jd,
                    research_bundle=bundle,
                    user=user,
                    retrieved_entries=retrieved,
                    style_profile=style_profile,
                    star_material=star_polishes,
                )
    else:
        async def generator():
            return await cover_letter.generate(
                jd=jd,
                research_bundle=bundle,
                user=user,
                retrieved_entries=retrieved,
                style_profile=style_profile,
                star_material=star_polishes,
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
    from .sub_agents import interview_questions

    bundle = await _load_session_bundle(session, storage)
    if bundle is None:
        raise ValueError(
            "No research bundle on session — forward a job URL before predicting questions."
        )
    bundle, shield_verdict = await _shield_bundle(bundle, "likely_questions")
    if shield_verdict and shield_verdict.recommended_action == "REJECT":
        raise ContentIntegrityRejected(shield_verdict, "scraped_jd")

    style_profile = await _get_style_profile(user, storage) or _fallback_style(user.user_id)

    jd = bundle.extracted_jd
    query = f"{jd.role_title} interview"
    retrieved = await storage.retrieve_relevant_entries(
        user_id=user.user_id, query=query, k=10,
        kind_weights=STAR_BOOST_KINDS,
    )

    company_name = bundle.company_research.company_name

    citation_ctx = await build_context(
        research_bundle=bundle,
        user_id=user.user_id,
        career_entries=retrieved,
    )

    # PROCESS Entry 45 — managed likely_questions routing.
    if settings.enable_managed_likely_questions:
        from .llm import call_in_session

        async def generator():
            try:
                return await call_in_session(
                    "likely_questions_managed",
                    jd=jd,
                    research_bundle=bundle,
                    user=user,
                    retrieved_entries=retrieved,
                    session_id=session.session_id,
                )
            except Exception as exc:
                log.warning(
                    "likely_questions_managed failed; falling back: %s", exc,
                )
                return await interview_questions.predict(
                    jd=jd,
                    research_bundle=bundle,
                    user=user,
                    retrieved_entries=retrieved,
                    citation_ctx=citation_ctx,
                )
    else:
        async def generator():
            return await interview_questions.predict(
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

    style_profile = await _get_style_profile(user, storage) or _fallback_style(user.user_id)
    ctx = await compute_job_search_context(user, storage)

    citation_ctx = await build_context(
        research_bundle=bundle,
        user_id=user.user_id,
        career_entries=[],
    )

    # PROCESS Entry 45 — managed salary_strategist routing.
    if settings.enable_managed_salary_strategist:
        from .llm import call_in_session
        try:
            return await call_in_session(
                "salary_strategist_managed",
                jd=bundle.extracted_jd,
                research_bundle=bundle,
                user=user,
                context=ctx,
                style_profile=style_profile,
                session_id=session.session_id,
            )
        except Exception as exc:
            log.warning(
                "salary_strategist_managed failed; falling back: %s", exc,
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

    (cv_result, cl_result, lq_result, sal_result,) = await asyncio.gather(
        cv_task, cl_task, lq_task, sal_task, return_exceptions=True
    )

    cv_out = cl_out = lq_out = sal_out = None
    files: dict[str, Path] = {}

    if isinstance(cv_result, Exception):
        log.error("full_prep draft_cv failed: %s", cv_result)
    else:
        cv_out, cv_docx, cv_pdf = cv_result
        files["cv_docx"] = cv_docx
        files["cv_pdf"] = cv_pdf

    if isinstance(cl_result, Exception):
        log.error("full_prep draft_cover_letter failed: %s", cl_result)
    else:
        cl_out, cl_docx, cl_pdf = cl_result
        files["cover_letter_docx"] = cl_docx
        files["cover_letter_pdf"] = cl_pdf

    if isinstance(lq_result, Exception):
        log.error("full_prep predict_questions failed: %s", lq_result)
    else:
        lq_out = lq_result

    if isinstance(sal_result, Exception):
        log.error("full_prep salary_advice failed: %s", sal_result)
    else:
        sal_out = sal_result

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

    style_profile = await _get_style_profile(user, storage) or _fallback_style(user.user_id)
    relevant = await storage.retrieve_relevant_entries(
        user_id=user.user_id, query=cleaned_msg[:200], k=5,
        kind_weights=STAR_BOOST_KINDS,
    )

    reply = await draft_reply.generate(
        incoming_message=cleaned_msg,
        user_intent_hint=user_intent,
        user=user,
        style_profile=style_profile,
        relevant_entries=relevant,
    )

    # Cross-application learning: record this recruiter interaction so
    # future draft_reply / salary_strategist calls can learn the user's
    # patterns. PROCESS Entry 43, Workstream E.
    try:
        from .memory import record_recruiter_interaction
        await record_recruiter_interaction(
            user_id=user.user_id,
            session_id=session_id,
            interaction_type=_interaction_type_from_intent(
                reply.user_intent_interpreted
            ),
            user_response_summary=reply.short_variant[:500],
        )
    except Exception as exc:
        log.debug("memory.record_recruiter_interaction skipped: %s", exc)

    return reply


def _interaction_type_from_intent(interpreted: str) -> str:
    """Map DraftReplyOutput.user_intent_interpreted -> memory enum."""
    mapping = {
        "accept_call": "phone_screen",
        "decline_politely": "decline",
        "ask_for_details": "initial_outreach",
        "negotiate_salary": "offer_negotiation",
        "defer": "initial_outreach",
        "other": "initial_outreach",
    }
    return mapping.get(interpreted, "initial_outreach")


# ---------------------------------------------------------------------------
# Phase 4 — Offer analysis (PROCESS Entry 43, Workstream F)
# ---------------------------------------------------------------------------


async def handle_analyse_offer(
    *,
    user: UserProfile,
    storage: Storage,
    session: Optional[Session] = None,
    file_id: Optional[str] = None,
    pdf_bytes: Optional[bytes] = None,
    text_pasted: Optional[str] = None,
):
    """Analyse a forwarded offer letter.

    Inputs (one required): `file_id` (already uploaded to Files API),
    `pdf_bytes` (will be uploaded), or `text_pasted` (plain text fallback).

    `session` is optional — when present, the most-recent ResearchBundle
    on it is included as gov_data + scraped-page documents for richer
    market comparison.
    """
    from .sub_agents import offer_analyst

    bundle: Optional[ResearchBundle] = None
    if session is not None:
        bundle = await _load_session_bundle(session, storage)

    analysis = await offer_analyst.analyse(
        user=user,
        research_bundle=bundle,
        file_id=file_id,
        pdf_bytes=pdf_bytes,
        text_pasted=text_pasted,
        session_id=session.session_id if session else None,
    )

    # Cross-application memory: an offer landed.
    try:
        from .memory import record_application_outcome, record_negotiation_result
        if session is not None:
            await record_application_outcome(
                user_id=user.user_id,
                session_id=session.session_id,
                company_name=analysis.company_name,
                role_title=analysis.role_title or "",
                outcome="offer_received",
                notes=analysis.market_comparison_note or None,
            )
            if analysis.base_salary_gbp is not None:
                # Best-effort numeric extraction; if it fails, skip record.
                try:
                    import re
                    digits = "".join(re.findall(r"\d+", analysis.base_salary_gbp.value_text))
                    if digits:
                        offered = int(digits[:6])  # cap nonsense
                        await record_negotiation_result(
                            user_id=user.user_id,
                            session_id=session.session_id,
                            company_name=analysis.company_name,
                            role_title=analysis.role_title or "",
                            asked_gbp=user.salary_target or user.salary_floor,
                            offered_gbp=offered,
                            final_gbp=None,
                            accepted=False,
                            notes="initial offer; awaiting response",
                        )
                except Exception:
                    pass
    except Exception as exc:
        log.debug("memory.record post-offer-analysis skipped: %s", exc)

    return analysis


# ---------------------------------------------------------------------------
# Phase 2.5 — Cross-verdict comparison + challenge (gaps #6 and #8)
# ---------------------------------------------------------------------------


async def handle_compare_verdicts(
    *,
    user: UserProfile,
    storage: Storage,
    limit: int = 10,
) -> "CompareVerdictsOutput":
    """Rank the user's recent apply-worthy sessions by composite score.

    Deterministic — no LLM call. The composite balances three signals:
      - verdict confidence (the verdict's own self-rated certainty)
      - freshness (older verdicts are less useful — sponsor data
        could have moved, the role may have been filled)
      - signal density (verdicts with more reasoning points + fewer
        stretch concerns are more substantive)

    Filters to positive labels (STRONG_GO, GO, TRY_ANYWAY) only —
    avoids ranking sessions the user should pass on.
    """
    from datetime import datetime, timezone

    from .schemas import CompareVerdictsOutput, RankedSession

    sessions = await storage.get_recent_sessions(user_id=user.user_id, limit=limit * 2)
    today = datetime.now(timezone.utc).replace(tzinfo=None)

    ranked: list[RankedSession] = []
    for s in sessions:
        if not s.verdict or not is_positive_verdict(s.verdict.decision):
            continue

        # Composite score in [0, 100].
        confidence = float(s.verdict.confidence_pct)

        # Freshness: linear decay from 1.0 at <=1 day to 0.5 at 14 days
        # to 0.2 at 28+ days. Older verdicts get penalised — the verdict
        # bundle ages faster than the JD itself does.
        age_days = max(0, (today - s.created_at).days)
        if age_days <= 1:
            freshness = 1.0
        elif age_days <= 14:
            freshness = 1.0 - 0.5 * (age_days - 1) / 13
        elif age_days <= 28:
            freshness = 0.5 - 0.3 * (age_days - 14) / 14
        else:
            freshness = 0.2

        # Signal density: more reasoning points = more substantive
        # verdict; stretch concerns drag it down (1 per concern).
        reasoning_count = len(s.verdict.reasoning)
        stretch_count = len(s.verdict.stretch_concerns)
        density = max(0.0, min(1.0, (reasoning_count - stretch_count) / 8.0))

        # Composite: 60% confidence, 25% freshness, 15% density.
        score = (
            confidence * 0.60
            + freshness * 100 * 0.25
            + density * 100 * 0.15
        )

        # Try to lift a role + company name out of phase1 payload.
        # Best-effort; missing fields render as "unknown".
        role_title = "unknown role"
        company_name = "unknown company"
        if s.phase1_output:
            extracted = s.phase1_output.get("extracted_jd") or {}
            company = s.phase1_output.get("company_research") or {}
            role_title = extracted.get("role_title", role_title) or role_title
            company_name = company.get("company_name", company_name) or company_name

        # Per-row rationale: just name the dominant driver. Always
        # include the age in days so the bot can surface staleness
        # uniformly across rows.
        if freshness < 0.5:
            rationale = (
                f"{s.verdict.decision} but the verdict is {age_days} days old — "
                f"re-forward before applying if you want fresh sponsor / CH data."
            )
        elif confidence >= 85 and freshness >= 0.8:
            rationale = (
                f"High confidence ({s.verdict.confidence_pct}%) and fresh "
                f"({age_days} day(s) old) — the strongest signal in your queue."
            )
        elif confidence >= 70:
            rationale = (
                f"Solid {s.verdict.decision} at {s.verdict.confidence_pct}% with "
                f"{stretch_count} concern(s); {age_days} day(s) old."
            )
        else:
            rationale = (
                f"Worth considering at {s.verdict.confidence_pct}% with "
                f"{stretch_count} stretch concern(s), "
                f"{age_days} day(s) old."
            )

        ranked.append(
            RankedSession(
                session_id=s.session_id,
                job_id=s.job_id,
                role_title=role_title,
                company_name=company_name,
                decision=s.verdict.decision,
                confidence_pct=s.verdict.confidence_pct,
                score=round(score, 1),
                headline=s.verdict.headline,
                rationale=rationale,
            )
        )

    ranked.sort(key=lambda r: r.score, reverse=True)
    ranked = ranked[:limit]

    return CompareVerdictsOutput(
        ranked=ranked,
        methodology=(
            "Composite = 60% verdict confidence + 25% freshness "
            "(linear decay over 28 days) + 15% signal density "
            "(reasoning points minus stretch concerns). Deterministic; "
            "the ranking is reproducible per (sessions, today)."
        ),
    )


async def handle_challenge_verdict(
    *,
    user: UserProfile,
    session: Session,
    challenge_text: str,
    storage: Storage,
) -> Verdict:
    """Re-run the verdict on the same research bundle, with the user's
    pushback text threaded into the verdict prompt.

    Architecture gap #8. The user has read the verdict, disagreed, and
    given a concrete reason ("you missed that they have a UK office",
    "the sponsor licence renewed last week"). We don't re-run Phase 1
    (the bundle is already there) — only the verdict, with a new
    `user_challenge_text` plumbed through.

    The challenge text is treated as a hint, not as ground truth. The
    verdict agent is instructed to either accept and re-rank, or
    explain why it's holding its position. Either is a valid outcome.
    """
    from .sub_agents import verdict as verdict_agent

    if not session.phase1_output:
        raise ValueError(
            "Cannot challenge a verdict without a stored Phase 1 bundle."
        )

    bundle = ResearchBundle.model_validate(session.phase1_output)

    # Reuse the same career-entry retrieval the original verdict used.
    retrieved = await storage.retrieve_relevant_entries(
        user_id=user.user_id,
        query=(
            f"{bundle.extracted_jd.role_title} "
            f"{' '.join(bundle.extracted_jd.required_skills[:5])}"
        ),
        k=8,
    )

    # Pull outcome history for calibration (same as the first verdict).
    prior_outcomes_text: Optional[str] = None
    try:
        from .memory.recall import recall_as_text

        prior_outcomes_text = await recall_as_text(
            user_id=user.user_id,
            kind="application_outcome",
            limit=10,
        )
    except Exception:  # pragma: no cover - defensive
        pass

    new_verdict = await verdict_agent.generate(
        research_bundle=bundle,
        user=user,
        retrieved_entries=retrieved,
        session_id=session.session_id,
        prior_outcomes_text=prior_outcomes_text,
        user_challenge_text=challenge_text,
    )

    await storage.save_verdict(session.session_id, new_verdict)
    return new_verdict


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
        if s.verdict and is_blocking_verdict(s.verdict.decision)
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


def _fallback_style(user_id: str) -> WritingStyleProfile:
    """Neutral style profile used when onboarding didn't collect samples.

    Threads the real user_id through so storage logs, audits, and later
    debugging can tell which user hit the fallback — "unknown" as a
    sentinel made log grepping harder without helping anyone.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return WritingStyleProfile(
        profile_id=f"fallback:{user_id}",
        user_id=user_id,
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
