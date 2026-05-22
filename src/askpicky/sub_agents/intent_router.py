"""Intent Router — classifies every user message into one of 11 intents.

System prompt verbatim from AGENTS.md §1.
Model: Opus 4.7 xhigh (misroute is costly).
"""

from __future__ import annotations

from ..prompts import load_prompt

from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import IntentRouterOutput, Session

SYSTEM_PROMPT = load_prompt("intent_router")


async def route(
    user_message: str,
    recent_messages: list[str],
    last_session: Optional[Session] = None,
    session_id: Optional[str] = None,
) -> IntentRouterOutput:
    # CLAUDE.md Rule 10: user messages are untrusted — Tier 1 only (the
    # router only decides a label, so residual risk is capped).
    from ..validators.content_shield import shield as shield_content

    cleaned_msg, _ = await shield_content(
        content=user_message,
        source_type="user_message",
        downstream_agent="intent_router",
    )
    cleaned_recent: list[str] = []
    for m in recent_messages[-4:]:
        c, _ = await shield_content(
            content=m,
            source_type="user_message",
            downstream_agent="intent_router",
        )
        cleaned_recent.append(c)

    context_lines = [f"USER MESSAGE: {cleaned_msg}"]
    if cleaned_recent:
        context_lines.append("RECENT CONTEXT (last 4 messages):")
        context_lines.extend(f"  {m}" for m in cleaned_recent)
    if last_session:
        # Session.verdict is always a Verdict model (storage.save_verdict
        # coerces on write), so no dict-vs-model branch needed.
        verdict_status = (
            last_session.verdict.decision if last_session.verdict else "NO_GO"
        )
        context_lines.append(
            f"LAST SESSION: job_url={last_session.job_url}, "
            f"intent={last_session.intent}, "
            f"verdict={verdict_status}"
        )

    return await call_agent(
        agent_name="intent_router",
        system_prompt=SYSTEM_PROMPT,
        user_input="\n".join(context_lines),
        output_schema=IntentRouterOutput,
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
    )
