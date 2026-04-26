"""Top-level pipeline coordination.

Implements all intent handlers. Bot handlers call into this module.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

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


PHASE_1_AGENTS: list[str] = [
    # Phase 1A (serial)
    "phase_1_jd_extractor",
    "phase_1_company_scraper_summariser",
    "companies_house",
    # Phase 1C (parallel — ordered by typical completion latency so the
    # visual ticking on the surface matches the order checkmarks
    # actually appear: parquet lookups fastest, then the scraper, then
    # the Opus xhigh agents, with red_flags last because it waits on
    # reviews).
    "sponsor_register",
    "soc_check",
    "salary_data",
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
        reviews as rev_agent,
        red_flags as rf_agent,
        ghost_job_detector,
        salary_data as sal_agent,
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

    timeout = settings.phase1_agent_timeout_s

    async def run_reviews():
        # Preferred path: Managed Agents reviews_investigator session.
        # Falls back to the legacy jobspy/playwright path on failure.
        if settings.enable_managed_reviews_investigator:
            try:
                from .llm import call_in_session
                managed_out = await asyncio.wait_for(
                    call_in_session(
                        "reviews_investigator",
                        company_name=company_research.company_name,
                        company_domain=company_research.company_domain,
                        session_id=session.session_id,
                    ),
                    timeout=max(timeout * 3, 120),  # MA sessions take longer
                )
                # Convert ReviewsInvestigatorOutput.excerpts (list of
                # managed.ReviewExcerpt) into the legacy
                # sub_agents.reviews.ReviewExcerpt shape downstream
                # red_flags expects.
                from .sub_agents.reviews import ReviewExcerpt as LegacyReviewExcerpt
                converted = [
                    LegacyReviewExcerpt(
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
                    len(converted), company_research.company_name,
                )
                await mark("reviews")
                if not reviews_future.done():
                    reviews_future.set_result(converted)
                return converted
            except (Exception, asyncio.TimeoutError) as exc:
                timed_out = isinstance(exc, asyncio.TimeoutError)
                log.warning(
                    "reviews_investigator failed (timed_out=%s); "
                    "falling back to legacy path: %s",
                    timed_out, exc,
                )
                # Fall through to legacy path below.

        try:
            result = await asyncio.wait_for(
                rev_agent.fetch(company_name=company_research.company_name),
                timeout=timeout,
            )
            await mark("reviews")
            if not reviews_future.done():
                reviews_future.set_result(result)
            return result
        except (Exception, asyncio.TimeoutError) as exc:
            timed_out = isinstance(exc, asyncio.TimeoutError)
            log.warning("reviews failed (timed_out=%s): %s", timed_out, exc)
            await mark("reviews")
            if not reviews_future.done():
                reviews_future.set_result([])
            return []

    async def run_salary():
        from .schemas import SalarySignals
        try:
            result = await asyncio.wait_for(
                sal_agent.fetch(
                    role=jd.role_title,
                    location=jd.location,
                    soc_code=jd.soc_code_guess,
                    posted_band=dict(jd.salary_band) if jd.salary_band else None,
                ),
                timeout=timeout,
            )
            await mark("salary_data")
            return result
        except (Exception, asyncio.TimeoutError) as exc:
            timed_out = isinstance(exc, asyncio.TimeoutError)
            log.warning("salary_data failed (timed_out=%s): %s", timed_out, exc)
            await mark("salary_data")
            return SalarySignals(
                sources_consulted=[],
                data_citations=[],
                source_status="UNREACHABLE",
            )

    async def run_sponsor():
        if user.user_type != "visa_holder":
            await mark("sponsor_register")
            return None
        try:
            result = await asyncio.wait_for(
                sr_agent.lookup(company_name=company_research.company_name),
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

    # Emitter flush is the caller's responsibility now (Wave 1 ADR-002).
    # bot/handlers.py calls emitter.close() → streamer.flush() on the
    # Telegram path; api/routes/sessions.py closes the SSEEmitter in
    # its `finally` block on the web path.

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

    if settings.enable_verdict_ensemble:
        # Money-no-object path: two parallel verdict calls, conservative
        # merge. Doubles spend but cuts the tail risk that a one-shot
        # Opus run mis-weights the hard-blocker set.
        #
        # Slot 2 swaps to the deep-research variant (Web Search + Web
        # Fetch) when `enable_verdict_ensemble_deep_research=True` —
        # that turns the ensemble from "two same-data runs" to "one
        # static-data run + one live-web-augmented run" which catches
        # signal the static bundle missed (recent news, leaver patterns).
        async def _v2():
            if settings.enable_verdict_ensemble_deep_research:
                try:
                    from .llm import call_in_session
                    return await call_in_session(
                        "verdict_deep_research",
                        user=user,
                        research_bundle=shielded_bundle,
                        session_id=session.session_id,
                    )
                except Exception as exc:
                    log.warning(
                        "verdict_deep_research failed; falling back to "
                        "standard second-slot verdict: %s", exc,
                    )
                    # Fall through to the symmetric path.
            return await verdict_agent.generate(
                research_bundle=shielded_bundle,
                user=user,
                retrieved_entries=retrieved,
                session_id=session.session_id,
            )

        v1, v2 = await asyncio.gather(
            verdict_agent.generate(
                research_bundle=shielded_bundle,
                user=user,
                retrieved_entries=retrieved,
                session_id=session.session_id,
            ),
            _v2(),
        )
        verdict = _ensemble_verdicts(v1, v2)
        log.info(
            "verdict ensemble%s: v1=%s(%d%%) v2=%s(%d%%) → %s(%d%%)",
            " (deep-research)" if settings.enable_verdict_ensemble_deep_research else "",
            v1.decision, v1.confidence_pct,
            v2.decision, v2.confidence_pct,
            verdict.decision, verdict.confidence_pct,
        )
    else:
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


def _ensemble_verdicts(v1: Verdict, v2: Verdict) -> Verdict:
    """Merge two verdict runs conservatively.

    Rules:
      - If either decision is NO_GO → the final decision is NO_GO
        (asymmetric: a hallucinated NO_GO is easier to spot and
        override than a hallucinated GO that gets the user to apply
        to a ghost).
      - Hard blockers union, deduped by (type, detail).
      - Stretch concerns union, deduped by (type, detail).
      - Reasoning points union — both runs' chains of evidence help
        the user see why.
      - Confidence: when decisions agree, take the mean; when they
        disagree, subtract half the gap (the disagreement itself is
        the signal to report less confidence).
      - Headline: prefer the NO_GO side's headline on disagreement
        (it names the blocker); otherwise v1's headline.
      - motivation_fit: take v1 (evaluations rarely disagree
        meaningfully run-to-run; no point building a merger).
      - estimated_callback_probability: take the worse of the two
        (LOW < MEDIUM < HIGH). None if either is None.
    """
    decision: str = "NO_GO" if "NO_GO" in (v1.decision, v2.decision) else "GO"

    def _union(a: list, b: list, key: Callable) -> list:
        seen: set = set()
        out: list = []
        for item in list(a) + list(b):
            k = key(item)
            if k in seen:
                continue
            seen.add(k)
            out.append(item)
        return out

    hard_blockers = _union(
        v1.hard_blockers, v2.hard_blockers,
        key=lambda b: (b.type, b.detail),
    )
    stretch_concerns = _union(
        v1.stretch_concerns, v2.stretch_concerns,
        key=lambda c: (c.type, c.detail),
    )
    reasoning = _union(
        v1.reasoning, v2.reasoning,
        key=lambda r: (r.claim, r.supporting_evidence),
    )

    if v1.decision == v2.decision:
        confidence_pct = (v1.confidence_pct + v2.confidence_pct) // 2
    else:
        gap = abs(v1.confidence_pct - v2.confidence_pct)
        confidence_pct = max(0, (v1.confidence_pct + v2.confidence_pct) // 2 - gap // 2)

    headline = v1.headline
    if v1.decision != v2.decision:
        # Use the NO_GO run's headline — it'll name the blocker.
        headline = v1.headline if v1.decision == "NO_GO" else v2.headline

    callback_rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    callback = None
    if v1.estimated_callback_probability and v2.estimated_callback_probability:
        worse = min(
            v1.estimated_callback_probability,
            v2.estimated_callback_probability,
            key=lambda x: callback_rank[x],
        )
        callback = worse

    return Verdict(
        decision=decision,  # type: ignore[arg-type]
        confidence_pct=confidence_pct,
        headline=headline,
        reasoning=reasoning,
        hard_blockers=hard_blockers,
        stretch_concerns=stretch_concerns,
        motivation_fit=v1.motivation_fit,
        estimated_callback_probability=callback,
    )


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
) -> tuple[CVOutput, Path, Path, Optional[Path]]:
    """Returns (cv, docx_path, pdf_path, latex_pdf_path).

    `latex_pdf_path` is None when pdflatex is missing, the writer
    agent failed, or the repair loop exhausted — see PROCESS.md
    Entry 37 for the additive contract.
    """
    from .sub_agents import cv_tailor_agentic as cv_tailor
    from .renderers import render_cv_docx, render_cv_pdf, render_latex_pdf

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
    # STAR boost: prefer validated star_polish + qa_answer narratives
    # over raw cv_bullet / project_note. See storage.STAR_BOOST_KINDS.
    from .storage import STAR_BOOST_KINDS
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

    # Both branches run the agentic FAISS-retrieval implementation
    # (cv_tailor.py is a re-export of cv_tailor_agentic since PROCESS
    # Entry 42 D5). The flag controls *wrapping*:
    #   - True  → call_in_session("cv_tailor_advisor", ...): Managed
    #             Agents wrapper (Sonnet executor + Opus advisor when
    #             the Advisor-tool surface is wired; today it delegates
    #             back to cv_tailor_agentic).
    #   - False → in-process call_agent_with_tools loop in cv_tailor_agentic.
    # Default off: managed agents are opt-in across this codebase.
    # PROCESS Entry 43 Workstream D + Entry 44.
    # Multi-provider routing (PROCESS Entry 44). When enabled and the
    # session's job_url maps to a non-Anthropic provider in
    # `ats_routing.ATS_TO_PROVIDER`, dispatch CV generation to that
    # provider via `cv_tailor_multi_provider.generate_via_provider`.
    # Anthropic-routed URLs (and all unmapped hosts) keep the existing
    # path. Provider misconfig (missing API key) raises
    # `ProviderUnavailable`, caught here and falls back to Anthropic so
    # the demo never goes down on a misrouted request.
    routed_provider = "anthropic"
    if settings.enable_multi_provider_cv_tailor and session.job_url:
        from .ats_routing import provider_for_url
        routed_provider = provider_for_url(session.job_url)
        if routed_provider != "anthropic":
            log.info(
                "cv_tailor multi-provider routing: url=%s -> provider=%s",
                session.job_url, routed_provider,
            )

    if routed_provider != "anthropic":
        from .sub_agents import cv_tailor_multi_provider as cv_mp
        from .llm_providers import ProviderUnavailable

        async def generator():
            try:
                return await cv_mp.generate_via_provider(
                    provider=routed_provider,
                    jd=jd,
                    research_bundle=bundle,
                    user=user,
                    style_profile=style_profile,
                    star_material=star_polishes,
                    citation_ctx=citation_ctx,
                    session_id=session.session_id,
                )
            except ProviderUnavailable as exc:
                log.warning(
                    "cv_tailor multi-provider (%s) unavailable: %s — "
                    "falling back to Anthropic agentic path.",
                    routed_provider, exc,
                )
                return await cv_tailor.generate(
                    jd=jd,
                    research_bundle=bundle,
                    user=user,
                    retrieved_entries=retrieved,
                    style_profile=style_profile,
                    star_material=star_polishes,
                    citation_ctx=citation_ctx,
                )
    elif settings.enable_managed_cv_tailor:
        from .llm import call_in_session

        async def generator():
            return await call_in_session(
                "cv_tailor_advisor",
                jd=jd,
                research_bundle=bundle,
                user=user,
                style_profile=style_profile,
                star_polishes=star_polishes,
                session_id=session.session_id,
            )
    else:
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

    # Additive third path: LaTeX-typeset PDF. Failures are silent; the
    # caller still gets the docx + reportlab pdf above.
    latex_pdf_path = await render_latex_pdf(
        cv,
        target_role=jd.role_title,
        session_id=session.session_id,
        out_dir=out_dir,
    )

    return cv, docx_path, pdf_path, latex_pdf_path


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
    from .storage import STAR_BOOST_KINDS
    retrieved = await storage.retrieve_relevant_entries(
        user_id=user.user_id, query=query, k=10,
        kind_weights=STAR_BOOST_KINDS,
    )

    company_name = bundle.company_research.company_name

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
    from .sub_agents import likely_questions

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
    from .storage import STAR_BOOST_KINDS
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

    style_profile = await _get_style_profile(user, storage) or _fallback_style(user.user_id)
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
            # handle_draft_cv returns (cv, docx, pdf, latex_pdf?) since the
            # LaTeX renderer landed (PROCESS Entry 37). The 4th element is
            # None when pdflatex is missing or the LaTeX path failed.
            cv_out, cv_docx, cv_pdf, cv_latex_pdf = result
            files["cv_docx"] = cv_docx
            files["cv_pdf"] = cv_pdf
            if cv_latex_pdf is not None:
                files["cv_latex_pdf"] = cv_latex_pdf
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

    style_profile = await _get_style_profile(user, storage) or _fallback_style(user.user_id)
    from .storage import STAR_BOOST_KINDS
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
        if s.verdict and s.verdict.decision == "NO_GO"
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
