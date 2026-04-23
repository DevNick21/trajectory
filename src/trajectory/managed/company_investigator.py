"""Managed Agents company investigator.

Genuine `client.beta.sessions.*` usage (not the dead stub previously in
`llm.py`). This is where Managed Agents is a real architectural win:
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
            raise ManagedInvestigatorFailed(f"agent setup failed: {exc}") from exc

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
    try:
        shielded_pages = await _shield_pages(result.scraped_pages)
    except ManagedInvestigatorFailed:
        await _safe_delete(client, ma_session_id)
        raise

    # Final JSON parse + Pydantic validation.
    if result.final_json is None:
        await _safe_delete(client, ma_session_id)
        raise ManagedInvestigatorFailed(
            "agent did not emit a parseable JSON final message"
        )

    try:
        investigator_output = InvestigatorOutput.model_validate(result.final_json)
    except Exception as exc:
        await _safe_delete(client, ma_session_id)
        raise ManagedInvestigatorFailed(
            f"final JSON failed InvestigatorOutput validation: {exc}"
        ) from exc

    # Citation-enforcement boundary — every snippet must appear in a
    # stored (shielded) page. Paraphrase → fail.
    try:
        research = _to_company_research(
            investigator_output,
            shielded_pages,
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

    # The SDK's .stream() is an async context manager on the sync path;
    # async clients expose the same shape.
    async with client.beta.sessions.events.stream(ma_session_id) as stream:
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
    job_url: str,
) -> CompanyResearch:
    """Convert + validate citations.

    Every `verbatim_snippet` across culture_claims, tech_stack_signals,
    team_size_signals, recent_activity_signals, and posted_salary_bands
    must appear in the text of a stored (shielded) page. Otherwise
    raise — paraphrasing breaks Trajectory's citation discipline.
    """
    page_texts = {p.url: p.text for p in shielded_pages}

    def _check(finding_list, label: str) -> None:
        for finding in finding_list:
            haystack = page_texts.get(finding.source_url)
            if haystack is None:
                raise ManagedInvestigatorFailed(
                    f"{label} citation references URL not fetched in "
                    f"this session: {finding.source_url}"
                )
            if finding.verbatim_snippet not in haystack:
                raise ManagedInvestigatorFailed(
                    f"{label} verbatim_snippet not found in fetched "
                    f"page {finding.source_url}: "
                    f"{finding.verbatim_snippet[:120]!r}"
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
        recent_activity_signals=[f.claim for f in output.recent_activity_signals],
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
