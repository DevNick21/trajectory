"""PA — Draft Reply.

Drafts a reply to a recruiter message in the user's voice.
System prompt verbatim from AGENTS.md §15.
"""

from __future__ import annotations

from ..prompts import load_prompt

import json
from typing import Literal, Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import (
    CareerEntry,
    DraftReplyOutput,
    UserProfile,
    WritingStyleProfile,
)
from ..validators.banned_phrases import contains_banned

SYSTEM_PROMPT = load_prompt("draft_reply")

UserIntent = Literal[
    "accept_call",
    "decline_politely",
    "ask_for_details",
    "negotiate_salary",
    "defer",
    "other",
]


def _post_validate(reply: DraftReplyOutput) -> list[str]:
    failures: list[str] = []
    combined = f"{reply.short_variant} {reply.long_variant}"
    for phrase in contains_banned(combined):
        failures.append(f"Banned phrase in draft reply: '{phrase}'")
    return failures


async def generate(
    incoming_message: str,
    user_intent_hint: str,
    user: UserProfile,
    style_profile: WritingStyleProfile,
    relevant_entries: Optional[list[CareerEntry]] = None,
) -> DraftReplyOutput:
    style_hint = (
        f"tone={style_profile.tone}, "
        f"formality={style_profile.formality_level}/10, "
        f"hedging={style_profile.hedging_tendency}"
    )

    entries_summary = []
    if relevant_entries:
        entries_summary = [
            {"entry_id": e.entry_id, "kind": e.kind, "text": e.raw_text[:300]}
            for e in relevant_entries[:5]
        ]

    user_input = json.dumps(
        {
            "incoming_message": incoming_message,
            "user_intent": user_intent_hint,
            "user_name": user.name,
            "salary_floor": user.salary_floor,
            "current_employment": user.current_employment,
            "writing_style": {
                "hint": style_hint,
                "signature_patterns": style_profile.signature_patterns[:5],
                "avoided_patterns": style_profile.avoided_patterns[:5],
                "examples": style_profile.examples[:3],
            },
            "relevant_entries": entries_summary,
        },
        default=str,
    )

    return await call_agent(
        agent_name="draft_reply",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=DraftReplyOutput,
        model=settings.opus_model_id,
        effort="xhigh",
        post_validate=_post_validate,
    )
