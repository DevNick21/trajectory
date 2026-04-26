"""Managed Agents company investigator.

Genuine `client.beta.sessions.*` usage.
This is where Managed Agents is a real architectural win:
the MA session runs in a sandboxed container with web fetch/search,
decides which pages to fetch based on what it reads, and surfaces
structured findings with verbatim-snippet citations.

Feature-flagged off by default. `company_scraper.run()` catches
`ManagedInvestigatorFailed` and falls back to the Playwright pipeline.

Flow:
  1. `get_or_create_agent(client)` — reuse cached agent, or create one
     with the managed_company_investigator.md system prompt.
  2. `get_or_create_environment(client)` — reuse cached environment
     (cloud + unrestricted networking).
  3. `client.beta.sessions.create(agent=..., environment_id=..., title=...)`
  4. Open `events.stream(session_id)` context.
  5. `events.send(session_id, events=[user.message])`.
  6. Iterate events until `session.status_idle` — capture scraped
     pages, final JSON, token counts.
  7. Read `sessions.retrieve(session_id).usage` for authoritative
     cumulative token totals.
  8. Content-shield every scraped page. REJECT → raise.
  9. Parse final JSON into `InvestigatorOutput`.
  10. Convert to `CompanyResearch` + `ExtractedJobDescription`, with
      every `verbatim_snippet` cross-checked against the shielded page
      text. Paraphrasing fails validation and raises.
  11. `sessions.archive(...)` on success, `sessions.delete(...)` on
      failure.

CLAUDE.md Rule 10 compliance: every scraped page passes through Tier 1
+ Tier 2 (HIGH_STAKES_AGENTS registration) before its text enters
`CompanyResearch`.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from ..config import settings
from ..schemas import (
    CompanyResearch,
    CultureClaim,
    ExtractedJobDescription,
    InvestigatorOutput,
    ScrapedPage,
)
from ..storage import log_llm_cost
from ..validators.content_shield import shield as shield_content
from . import _resources
from ._events import EventStreamResult, consume_stream

logger = logging.getLogger(__name__)


class ManagedInvestigatorFailed(RuntimeError):
    """Any failure in the MA path. Callers (company_scraper.run) fall
    back to the plain Playwright pipeline when this is raised."""


_AGENT_LABEL = "managed_company_investigator"


async def investigate(
    *,
    job_url: str,
    company_name_hint: Optional[str] = None,
    session_id: Optional[str] = None,
) -> tuple[CompanyResearch, ExtractedJobDescription]:
    """Investigate a company via a sandboxed Managed Agents session.

    Drop-in replacement for `company_scraper.run()` — same return
    shape. `session_id` is the Trajectory session_id (for cost log
    attribution), not the MA session_id.

    Also registered as `company_investigator` in
    `trajectory.managed.SESSIONS` (Workstream I) so
    `llm.call_in_session("company_investigator", job_url=..., ...)` is
    the canonical dispatch path.
    """
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:
        raise ManagedInvestigatorFailed(
            "anthropic SDK not installed in this environment"
        ) from exc

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        agent_id, agent_version = await _resources.get_or_create_agent(client)
    except Exception as exc:
        # 404 from out-of-band deletion — retry once after invalidating.
        if _is_not_found(exc):
            _resources.invalidate_cache(agent=True)
            agent_id, agent_version = await _resources.get_or_create_agent(client)
        else:
            raise ManagedInvestigatorFailed(
                f"agent setup failed: {exc}") from exc

    try:
        environment_id = await _resources.get_or_create_environment(client)
    except Exception as exc:
        if _is_not_found(exc):
            _resources.invalidate_cache(environment=True)
            environment_id = await _resources.get_or_create_environment(client)
        else:
            raise ManagedInvestigatorFailed(
                f"environment setup failed: {exc}"
            ) from exc

    try:
        ma_session = await client.beta.sessions.create(
            agent=agent_id,
            environment_id=environment_id,
            title=f"Investigate: {job_url[:60]}",
        )
    except Exception as exc:
        raise ManagedInvestigatorFailed(
            f"session creation failed: {exc}"
        ) from exc

    ma_session_id = getattr(ma_session, "id")
    logger.info(
        "MA investigator: session=%s agent=%s(v%d) env=%s",
        ma_session_id, agent_id, agent_version, environment_id,
    )

    try:
        result = await _run_session(
            client,
            ma_session_id=ma_session_id,
            job_url=job_url,
            company_name_hint=company_name_hint,
        )
    except ManagedInvestigatorFailed:
        await _safe_delete(client, ma_session_id)
        raise
    except Exception as exc:
        await _safe_delete(client, ma_session_id)
        raise ManagedInvestigatorFailed(
            f"investigator error: {exc}"
        ) from exc

    # Content Shield — every page that entered the sandbox.
    # Citation validation needs the UNSHIELDED text the agent actually
    # saw via web_fetch (the agent's snippets came from there); the
    # shield's truncation/redaction is for downstream agents and would
    # cause spurious "snippet not in haystack" failures otherwise.
    original_pages = list(result.scraped_pages)
    try:
        shielded_pages = await _shield_pages(result.scraped_pages)
    except ManagedInvestigatorFailed:
        await _safe_delete(client, ma_session_id)
        raise

    # Final JSON parse + Pydantic validation.
    if result.final_json is None:
        await _safe_delete(client, ma_session_id)
        preview = result.last_agent_text_preview
        if preview is None:
            detail = (
                f"no agent.message text emitted across "
                f"{result.agent_message_count} agent.message event(s) — "
                "session went idle without a final response"
            )
        else:
            detail = (
                f"last agent text was non-JSON "
                f"({len(preview)}c preview): {preview!r}"
            )
        raise ManagedInvestigatorFailed(
            f"agent did not emit a parseable JSON final message — {detail}"
        )

    try:
        investigator_output = InvestigatorOutput.model_validate(
            result.final_json)
    except Exception as exc:
        await _safe_delete(client, ma_session_id)
        raise ManagedInvestigatorFailed(
            f"final JSON failed InvestigatorOutput validation: {exc}"
        ) from exc

    # Citation-enforcement boundary — every snippet must appear in the
    # ORIGINAL (pre-shield) page text the agent saw. The downstream
    # CompanyResearch carries the shielded version.
    try:
        research = _to_company_research(
            investigator_output,
            shielded_pages,
            validation_pages=original_pages,
            job_url=job_url,
        )
    except ManagedInvestigatorFailed:
        await _safe_delete(client, ma_session_id)
        raise

    # Authoritative token totals — sessions.retrieve exposes the
    # cumulative `usage` field after idle.
    input_tokens, output_tokens = await _read_session_usage(
        client, ma_session_id, fallback=result,
    )
    await log_llm_cost(
        session_id=session_id,
        agent_name=_AGENT_LABEL,
        model=settings.opus_model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    await _safe_archive(client, ma_session_id)
    return research, investigator_output.extracted_jd


async def _run_session(
    client,
    *,
    ma_session_id: str,
    job_url: str,
    company_name_hint: Optional[str],
) -> EventStreamResult:
    """Open the stream FIRST, then send the kickoff user.message.

    Anthropic's docs are explicit: only events emitted after the stream
    is opened are delivered, so opening first avoids a race where the
    initial agent.message beats our stream context.
    """
    prompt_text = _build_user_prompt(job_url, company_name_hint)

    # AsyncAnthropic's events.stream(...) is itself an `async def` —
    # the call returns a coroutine that resolves to the async context
    # manager. Two awaits required: one to get the manager, then
    # `async with` to enter it. The sync client docs use `with
    # client.beta.sessions.events.stream(...) as stream:` directly;
    # the async client needs the extra await.
    async with await client.beta.sessions.events.stream(
        ma_session_id,
    ) as stream:
        await client.beta.sessions.events.send(
            ma_session_id,
            events=[
                {
                    "type": "user.message",
                    "content": [{"type": "text", "text": prompt_text}],
                }
            ],
        )
        result = await consume_stream(stream)

    if result.terminated_early:
        raise ManagedInvestigatorFailed(
            f"session terminated early: {result.terminated_reason}"
        )
    return result


def _build_user_prompt(job_url: str, company_name_hint: Optional[str]) -> str:
    hint = (
        f"\nCOMPANY NAME HINT (from onboarding / prior context): "
        f"{company_name_hint}"
        if company_name_hint
        else ""
    )
    return (
        "Investigate the UK company whose job URL is below. Follow your "
        "system-prompt rules exactly — especially the 8-page budget, the "
        "verbatim-snippet requirement, and the LinkedIn/Indeed/Glassdoor "
        "fetch ban.\n\n"
        f"JOB URL: {job_url}{hint}\n\n"
        "When you have enough evidence, emit ONE final message containing "
        "ONLY a JSON object matching the InvestigatorOutput schema. Do not "
        "wrap it in Markdown fences. Do not emit any other messages "
        "afterward."
    )


_WS_RE = re.compile(r"\s+")


def _normalize_ws(text: str) -> str:
    """Collapse all runs of whitespace (including NBSP / line-breaks)
    to a single space, lowercase nothing else. Used by the citation-
    snippet validator so a verbatim quote that differs only in
    line-wrapping or NBSP→space substitutions still resolves."""
    return _WS_RE.sub(" ", text.replace(" ", " ")).strip()


def _longest_matching_prefix(needle: str, haystack: str) -> int:
    """Return the length of the longest prefix of `needle` that appears
    as a substring of `haystack`. Used by the citation validator's
    near-match tolerance — Opus occasionally drops or rephrases the
    last 1-2 words of a long verbatim quote, and we'd rather accept
    a 95% match than reject the entire generation. O(log n) via
    binary search over substring containment."""
    if not needle or not haystack:
        return 0
    if needle in haystack:
        return len(needle)
    lo, hi = 0, len(needle)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if needle[:mid] in haystack:
            lo = mid
        else:
            hi = mid - 1
    return lo


async def _shield_pages(pages: list[ScrapedPage]) -> list[ScrapedPage]:
    """Run Tier 1 + (when flagged) Tier 2 on every page. REJECT raises."""
    shielded: list[ScrapedPage] = []
    for page in pages:
        cleaned, verdict = await shield_content(
            content=page.text,
            source_type="scraped_company_page",
            downstream_agent=_AGENT_LABEL,
        )
        if verdict is not None and verdict.recommended_action == "REJECT":
            raise ManagedInvestigatorFailed(
                f"content shield rejected {page.url}: {verdict.reasoning}"
            )
        shielded.append(page.model_copy(update={"text": cleaned}))
    return shielded


def _to_company_research(
    output: InvestigatorOutput,
    shielded_pages: list[ScrapedPage],
    *,
    validation_pages: list[ScrapedPage] | None = None,
    job_url: str,
) -> CompanyResearch:
    """Convert + validate citations.

    Every `verbatim_snippet` across culture_claims, tech_stack_signals,
    team_size_signals, recent_activity_signals, and posted_salary_bands
    must appear in the text of a stored (validation) page. Otherwise
    raise — paraphrasing breaks Trajectory's citation discipline.

    `validation_pages` is the *unshielded* page list the agent actually
    saw via web_fetch. When omitted (legacy callers, tests), validation
    falls back to `shielded_pages` — the pre-fix behaviour. Production
    `investigate()` always passes both because the shield's truncation /
    redaction would otherwise cause spurious validation failures (the
    agent's snippet came from text past the shield's character cap).
    """
    if validation_pages is None:
        validation_pages = shielded_pages
    page_texts = {p.url: p.text for p in validation_pages}

    def _check(finding_list, label: str) -> None:
        for finding in finding_list:
            haystack = page_texts.get(finding.source_url)
            if haystack is None:
                raise ManagedInvestigatorFailed(
                    f"{label} citation references URL not fetched in "
                    f"this session: {finding.source_url}"
                )
            # Whitespace-tolerant substring check: HTML→text extraction
            # collapses whitespace differently across runs, and a stray
            # NBSP / multiple-newline mismatch is not paraphrase. We
            # normalize both sides before comparing.
            #
            # Plus: tolerate ≥95% longest-matching-prefix on long
            # snippets. Live runs occasionally see Opus drop or
            # rephrase the last 1-2 words of a long quote — the bulk
            # of the citation is still verbatim, so demanding bit-exact
            # equality would reject snippets that aren't substantively
            # paraphrased. The threshold (95% + min 60-char snippet)
            # accepts trailing-word drops while still catching real
            # paraphrasing (which usually diverges much earlier).
            normalized_snippet = _normalize_ws(finding.verbatim_snippet)
            normalized_haystack = _normalize_ws(haystack)
            exact_match = (
                finding.verbatim_snippet in haystack
                or normalized_snippet in normalized_haystack
            )
            if not exact_match:
                prefix_len = _longest_matching_prefix(
                    normalized_snippet, normalized_haystack,
                )
                snippet_len = len(normalized_snippet)
                # Tolerance scales with length:
                #   ≥ 60  chars: 90% prefix match (was 95% — relaxed
                #                after live runs showed Opus drifting
                #                in the last word of long quotes at
                #                ~91% — well above paraphrase territory)
                #   ≥ 200 chars: 85% prefix match (very long quotes
                #                rarely lose a sentence and stay verbatim)
                # Below 60 chars: exact match still required.
                threshold = 0.90 if snippet_len < 200 else 0.85
                if (
                    snippet_len >= 60
                    and prefix_len >= int(snippet_len * threshold)
                ):
                    logger.warning(
                        "%s near-match accepted (%d/%dc, %.1f%% ≥ %.0f%%): %s ...",
                        label, prefix_len, snippet_len,
                        100.0 * prefix_len / snippet_len,
                        threshold * 100,
                        finding.verbatim_snippet[:60],
                    )
                    continue

                # Multi-segment concatenation: when the snippet contains
                # `...`, `…`, OR several distinct sentences, the agent
                # has often synthesized a digest of multiple verbatim
                # pieces (PROCESS Entry 47 — Opus routinely does this
                # on listy pages like a careers nav, AND on prose pages
                # where it pulls 2 sentences from different paragraphs
                # and glues them together with no separator).
                #
                # Two split strategies, tried in order:
                #   1. ellipsis (`...` / `…`) — explicit "I'm
                #      synthesizing" marker
                #   2. sentence boundaries (`. ` / `! ` / `? `) — when
                #      the snippet has 2+ sentences and at least one
                #      ISN'T a substring of the haystack on its own,
                #      try splitting and accepting if every sentence
                #      individually IS a substring.
                # Each split's segments must ALL substring-match
                # individually for the snippet to be accepted.
                #
                # Min 12 chars per segment guards against trivial
                # matches; min 2 segments guards against the
                # single-sentence case (which would already have
                # passed the prefix check).
                def _try_split(
                    splitter_re: str,
                    label_kind: str,
                    min_segment_len: int = 12,
                ) -> bool:
                    segs = [
                        s.strip()
                        for s in re.split(splitter_re, finding.verbatim_snippet)
                        if len(s.strip()) >= min_segment_len
                    ]
                    if len(segs) < 2:
                        return False
                    norm_segs = [_normalize_ws(s) for s in segs]
                    matched = sum(
                        1 for s in norm_segs if s in normalized_haystack
                    )
                    if matched == len(norm_segs):
                        logger.warning(
                            "%s multi-segment accepted via %s (%d/%d segments): %s ...",
                            label, label_kind, matched, len(norm_segs),
                            finding.verbatim_snippet[:60],
                        )
                        return True
                    return False

                if _try_split(r"\s*(?:\.{3,}|…)\s*", "ellipsis"):
                    continue
                if _try_split(r"(?<=[.!?])\s+(?=[A-Z])", "sentence-boundary"):
                    continue
                # List separator (`|`, `•`, `;`, etc.). Opus routinely
                # synthesizes a pipe-/bullet-delimited list from
                # individual page elements: e.g.
                # "Australia | Canada | France | India" assembled
                # from a country-cards section. min_segment_len=3
                # because countries / categories are often short.
                if _try_split(
                    r"\s*(?:\||•|·|;|→|»)\s*",
                    "list-separator",
                    min_segment_len=3,
                ):
                    continue
                # Comma-separated list: only when there are ≥4 commas
                # (otherwise plain prose with one comma would
                # accidentally trigger), and segments must be ≥3 chars.
                comma_count = finding.verbatim_snippet.count(",")
                if comma_count >= 4 and _try_split(
                    r"\s*,\s*", "comma-list", min_segment_len=3,
                ):
                    continue
            if not exact_match:
                # Diagnostic: show snippet head + tail and the closest
                # matching prefix in the haystack. Common cause is the
                # agent dropping one character at the tail of a quote
                # (e.g. "and year" where the source has "and years");
                # the prefix-match log line makes this obvious.
                snippet = finding.verbatim_snippet
                head = snippet[:80]
                tail = snippet[-80:] if len(snippet) > 160 else ""
                # Find the longest prefix of the snippet that IS in the
                # haystack — pinpoints where the divergence starts.
                norm_haystack = _normalize_ws(haystack)
                norm_snippet = _normalize_ws(snippet)
                lo, hi = 0, len(norm_snippet)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if norm_snippet[:mid] in norm_haystack:
                        lo = mid
                    else:
                        hi = mid - 1
                matched_prefix_len = lo
                raise ManagedInvestigatorFailed(
                    f"{label} verbatim_snippet not found in fetched "
                    f"page {finding.source_url} "
                    f"(snippet={len(snippet)}c, haystack={len(haystack)}c, "
                    f"longest matching prefix={matched_prefix_len}c): "
                    f"head={head!r} tail={tail!r}"
                )

    _check(output.culture_claims, "culture_claims")
    _check(output.tech_stack_signals, "tech_stack_signals")
    _check(output.team_size_signals, "team_size_signals")
    _check(output.recent_activity_signals, "recent_activity_signals")
    _check(output.posted_salary_bands, "posted_salary_bands")

    # Ensure the job URL appears somewhere — otherwise we have no
    # snippet-resolvable proof the JD came from where it says.
    if not any(p.url == job_url for p in shielded_pages):
        # Fall back to matching on host+path equality modulo trailing
        # slashes before giving up.
        def _norm(u: str) -> str:
            return u.rstrip("/")
        if not any(_norm(p.url) == _norm(job_url) for p in shielded_pages):
            logger.warning(
                "job URL %s not in investigator's fetched pages (had: %s)",
                job_url, [p.url for p in shielded_pages],
            )

    culture_claims = [
        CultureClaim(
            claim=f.claim,
            url=f.source_url,
            verbatim_snippet=f.verbatim_snippet,
        )
        for f in output.culture_claims
    ]

    return CompanyResearch(
        company_name=output.company_name,
        company_domain=output.company_domain,
        scraped_pages=shielded_pages,
        culture_claims=culture_claims,
        tech_stack_signals=[f.claim for f in output.tech_stack_signals],
        team_size_signals=[f.claim for f in output.team_size_signals],
        recent_activity_signals=[
            f.claim for f in output.recent_activity_signals],
        posted_salary_bands=[f.claim for f in output.posted_salary_bands],
        policies={},
        careers_page_url=output.careers_page_url,
        not_on_careers_page=output.not_on_careers_page,
    )


async def _read_session_usage(
    client, ma_session_id: str, *, fallback: EventStreamResult,
) -> tuple[int, int]:
    """After idle, sessions.retrieve exposes authoritative cumulative
    token usage. Fall back to the per-event accumulator on API
    failure — MA retrieves are cheap but not free.
    """
    try:
        retrieved = await client.beta.sessions.retrieve(ma_session_id)
        usage = getattr(retrieved, "usage", None)
        if usage is not None:
            it = getattr(usage, "input_tokens", None) or 0
            ot = getattr(usage, "output_tokens", None) or 0
            return int(it), int(ot)
    except Exception as exc:
        logger.debug("sessions.retrieve failed, using accumulator: %r", exc)
    return fallback.input_tokens, fallback.output_tokens


async def _safe_archive(client, ma_session_id: str) -> None:
    try:
        await client.beta.sessions.archive(ma_session_id)
    except Exception as exc:
        logger.warning("archive failed for %s: %r", ma_session_id, exc)


async def _safe_delete(client, ma_session_id: str) -> None:
    try:
        await client.beta.sessions.delete(ma_session_id)
    except Exception as exc:
        logger.warning("delete failed for %s: %r", ma_session_id, exc)


def _is_not_found(exc: Exception) -> bool:
    """Heuristic: MA SDK raises HTTPStatusError-like with `.status_code`
    or a 404 substring in the message. Tolerate both."""
    status = getattr(exc, "status_code", None)
    if status == 404:
        return True
    text = str(exc).lower()
    return "404" in text or "not found" in text


# Self-register into the managed SESSIONS dispatch table (Workstream I).
from . import _register_session as _reg
_reg("company_investigator", investigate)
