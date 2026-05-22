"""Onboarding — Writing Style Extractor.

Builds WritingStyleProfile from the user's pasted samples.
System prompt verbatim from AGENTS.md §9.
"""

from __future__ import annotations

from ..prompts import load_prompt

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import WritingStyleProfile, WritingStyleProfileLLMOutput

SYSTEM_PROMPT = load_prompt("style_extractor")


async def extract(
    user_id: str,
    samples: list[str],
    session_id: Optional[str] = None,
) -> WritingStyleProfile:
    # Two filters run over writing samples before they reach Opus:
    #   1. PII scrubber — strip email / phone / NINO / postcode / card /
    #      DOB so the WritingStyleProfile can't end up citing personal
    #      identifiers in generated cover letters.
    #   2. Content Shield Tier 1 (CLAUDE.md Rule 10) — strip known
    #      prompt-injection patterns.
    # Order matters: PII first (pattern is narrow), shield second
    # (it also strips zero-width / bidi chars that could otherwise
    # smuggle PII past step 1).
    from ..validators.content_shield import shield as shield_content
    from ..validators.pii_scrubber import scrub as scrub_pii

    cleaned_samples: list[str] = []
    pii_redactions: list[str] = []
    for s in samples:
        pii_result = scrub_pii(s)
        pii_redactions.extend(pii_result.redactions)
        cleaned, _ = await shield_content(
            content=pii_result.cleaned_text,
            source_type="writing_sample",
            downstream_agent="style_extractor",
        )
        cleaned_samples.append(cleaned)

    if pii_redactions:
        import logging
        logging.getLogger(__name__).info(
            "style_extractor: scrubbed %d PII item(s) from %d sample(s) "
            "before Opus call (types: %s)",
            len(pii_redactions),
            len(samples),
            ", ".join(sorted(set(pii_redactions))),
        )

    user_input = json.dumps(
        {
            "sample_count": len(cleaned_samples),
            "samples": cleaned_samples,
        },
        default=str,
    )

    profile_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # The LLM emits only the fields it actually produces — identity and
    # timestamps are injected by us afterwards. Shrinks the tool schema
    # and removes the invitation to invent IDs that don't exist.
    raw = await call_agent(
        agent_name="style_extractor",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=WritingStyleProfileLLMOutput,
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
    )

    return WritingStyleProfile(
        profile_id=profile_id,
        user_id=user_id,
        source_sample_ids=[],
        sample_count=len(samples),
        created_at=now,
        updated_at=now,
        **raw.model_dump(),
    )
