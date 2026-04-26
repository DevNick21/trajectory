"""Reviews investigator — Managed Agents session that replaces the
no-op `sub_agents/reviews.py` jobspy path.

Lifecycle mirrors `company_investigator.py`. The investigator agent
runs in a sandboxed environment with web tools; the system prompt
(`prompts/managed_reviews_investigator.md`) lists allowed and banned
sources. Output is `ReviewsInvestigatorOutput` (defined inline below
since it's only consumed here).

PROCESS Entry 43, Workstream C+I.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from ..config import settings
from ..prompts import load_prompt
from ..storage import log_llm_cost
from ..validators.content_shield import shield as shield_content
from . import _register_session, _resources
from ._events import consume_stream

logger = logging.getLogger(__name__)


class ReviewsInvestigatorFailed(RuntimeError):
    """Any failure in the MA reviews path. Callers should fall back to
    an empty review list and continue Phase 1."""


class ReviewExcerpt(BaseModel):
    source: str
    rating: Optional[float] = None
    title: Optional[str] = None
    text: str
    url: Optional[str] = None


class ReviewsInvestigatorOutput(BaseModel):
    company_name: str
    excerpts: list[ReviewExcerpt] = Field(default_factory=list)
    investigation_notes: str = ""


_AGENT_NAME = "trajectory-reviews-investigator"
_AGENT_LABEL = "managed_reviews_investigator"
_AGENT_TOOLS: list[dict[str, Any]] = [{"type": "agent_toolset_20260401"}]


async def run(
    *,
    company_name: str,
    company_domain: Optional[str] = None,
    session_id: Optional[str] = None,
) -> ReviewsInvestigatorOutput:
    """Investigate a company's employee reviews via a sandboxed session.

    Returns a `ReviewsInvestigatorOutput`. On failure, raises
    `ReviewsInvestigatorFailed` — callers should treat reviews as
    empty and proceed.
    """
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:
        raise ReviewsInvestigatorFailed(
            "anthropic SDK not installed"
        ) from exc

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    system_prompt = load_prompt("managed_reviews_investigator")

    try:
        agent_id, agent_version = await _resources.get_or_create_named_agent(
            client,
            name=_AGENT_NAME,
            system_prompt=system_prompt,
            tools=_AGENT_TOOLS,
        )
    except Exception as exc:
        raise ReviewsInvestigatorFailed(
            f"reviews agent setup failed: {exc}"
        ) from exc

    try:
        environment_id = await _resources.get_or_create_environment(client)
    except Exception as exc:
        raise ReviewsInvestigatorFailed(
            f"environment setup failed: {exc}"
        ) from exc

    try:
        # Mirror `company_investigator.py:117` — pass `agent=<id>` as a
        # bare string. The dict form `{"id": ..., "version": ...}` was
        # rejected by the API live with
        # `agent.selector.type: Field required` (PROCESS Entry 45
        # follow-up). Bare ID resolves to the latest version of the
        # named agent, which is what we want here too.
        ma_session = await client.beta.sessions.create(
            agent=agent_id,
            environment_id=environment_id,
            title=f"Reviews: {company_name[:50]}",
        )
    except Exception as exc:
        raise ReviewsInvestigatorFailed(
            f"session creation failed: {exc}"
        ) from exc

    ma_session_id = getattr(ma_session, "id")
    logger.info(
        "MA reviews: session=%s agent=%s(v%d)",
        ma_session_id, agent_id, agent_version,
    )

    prompt_text = (
        f"Investigate UK employee reviews for the company below. Follow "
        f"your system prompt exactly — use the priority list, respect the "
        f"banned-source list, and emit ONLY the JSON final message.\n\n"
        f"COMPANY NAME: {company_name}"
    )
    if company_domain:
        prompt_text += f"\nCOMPANY DOMAIN: {company_domain}"

    try:
        async with await client.beta.sessions.events.stream(ma_session_id) as stream:
            await client.beta.sessions.events.send(
                ma_session_id,
                events=[{
                    "type": "user.message",
                    "content": [{"type": "text", "text": prompt_text}],
                }],
            )
            result = await consume_stream(stream)
    except Exception as exc:
        await _safe_delete(client, ma_session_id)
        raise ReviewsInvestigatorFailed(
            f"reviews investigator session error: {exc}"
        ) from exc

    if result.terminated_early:
        await _safe_delete(client, ma_session_id)
        raise ReviewsInvestigatorFailed(
            f"session terminated early: {result.terminated_reason}"
        )
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
        raise ReviewsInvestigatorFailed(
            f"agent did not emit a parseable JSON final message — {detail}"
        )

    try:
        output = ReviewsInvestigatorOutput.model_validate(result.final_json)
    except ValidationError as exc:
        await _safe_delete(client, ma_session_id)
        raise ReviewsInvestigatorFailed(
            f"final JSON failed validation: {exc}"
        ) from exc

    # Content-shield each review excerpt — we want injection patterns
    # cleaned out of any text that flows into downstream agents
    # (red_flags_detector, verdict).
    shielded_excerpts: list[ReviewExcerpt] = []
    for ex in output.excerpts:
        cleaned, _verdict = await shield_content(
            content=ex.text,
            source_type="scraped_company_page",
            downstream_agent=_AGENT_LABEL,
        )
        shielded_excerpts.append(ex.model_copy(update={"text": cleaned}))
    output = output.model_copy(update={"excerpts": shielded_excerpts})

    # Authoritative cumulative usage from the session.
    try:
        sess = await client.beta.sessions.retrieve(ma_session_id)
        usage = getattr(sess, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    except Exception:
        input_tokens = output_tokens = 0

    await log_llm_cost(
        session_id=session_id,
        agent_name=_AGENT_LABEL,
        model=settings.opus_model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    await _safe_archive(client, ma_session_id)
    logger.info(
        "MA reviews complete: company=%s excerpts=%d",
        output.company_name, len(output.excerpts),
    )
    return output


async def _safe_archive(client, ma_session_id: str) -> None:
    try:
        await client.beta.sessions.archive(ma_session_id)
    except Exception as exc:  # pragma: no cover
        logger.warning("session.archive(%s) failed: %s", ma_session_id, exc)


async def _safe_delete(client, ma_session_id: str) -> None:
    try:
        await client.beta.sessions.delete(ma_session_id)
    except Exception as exc:  # pragma: no cover
        logger.warning("session.delete(%s) failed: %s", ma_session_id, exc)


_register_session("reviews_investigator", run)
