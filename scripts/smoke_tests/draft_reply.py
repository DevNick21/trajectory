"""Smoke test — draft_reply.generate on a recruiter message.

Input first passes through Tier 1 content shield (orchestrator-style),
then the Opus xhigh generator produces a DraftReplyOutput.

Set SMOKE_DRAFT_REPLY_MOCK=1 to skip Opus.

Cost: ~$0.20 live, $0 mock.
"""

from __future__ import annotations

import os

from ._common import (
    SmokeResult,
    build_synthetic_writing_style,
    build_test_user,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "draft_reply"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.20

_RECRUITER_MSG = (
    "Hi, I'm Sarah from TalentLoop. I came across your GitHub and "
    "wanted to reach out about a Senior Python role paying £85-95k "
    "at a Series B fintech in Shoreditch. Hybrid, 3 days in office. "
    "Would you be open to a 20 min call this week?"
)


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    mock = os.getenv("SMOKE_DRAFT_REPLY_MOCK", "").lower() in {"1", "true", "yes"}
    if not mock:
        missing = require_anthropic_key()
        if missing:
            return [], [missing], 0.0

    user = build_test_user("uk_resident")
    style = build_synthetic_writing_style(user.user_id)

    messages: list[str] = []
    failures: list[str] = []

    if mock:
        messages.append(f"MOCK: skipped Opus; would reply as user={user.name}")
        return messages, failures, 0.0

    from trajectory.sub_agents import draft_reply
    from trajectory.validators.content_shield import tier1
    from trajectory.validators.banned_phrases import contains_banned

    shielded = tier1(_RECRUITER_MSG).cleaned_text

    try:
        reply = await draft_reply.generate(
            incoming_message=shielded,
            user_intent_hint="ask_for_details",
            user=user,
            style_profile=style,
            relevant_entries=None,
        )
    except Exception as exc:
        failures.append(f"draft_reply.generate raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"intent={reply.user_intent_interpreted} "
        f"short_len={len(reply.short_variant)} long_len={len(reply.long_variant)}"
    )
    if reply.user_intent_interpreted not in {
        "accept_call", "decline_politely", "ask_for_details",
        "negotiate_salary", "defer", "other",
    }:
        failures.append(f"unexpected intent: {reply.user_intent_interpreted!r}")
    if len(reply.short_variant.split()) > 100:
        failures.append(
            f"short_variant too long: {len(reply.short_variant.split())} words"
        )
    for phrase in contains_banned(reply.short_variant + "\n" + reply.long_variant):
        failures.append(f"banned phrase in draft reply: {phrase!r}")

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
