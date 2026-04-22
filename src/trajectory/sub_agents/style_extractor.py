"""Onboarding — Writing Style Extractor.

Builds WritingStyleProfile from the user's pasted samples.
System prompt verbatim from AGENTS.md §9.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import WritingStyleProfile

SYSTEM_PROMPT = """\
Build a compact writing-style profile from the user's pasted
professional samples (emails, cover letters, LinkedIn messages,
Slack messages, etc.).

Produce:

- tone: 3-5 words, concrete. "Warm but direct" yes. "Professional" no.
- sentence_length_pref: short | medium | varied | long
- formality_level: 1-10, based on contractions, slang, salutations,
  signoffs, use of passive voice
- hedging_tendency: direct | moderate | diplomatic
- signature_patterns: phrases appearing 2+ times, or distinctive
  single uses. Must be verbatim.
- avoided_patterns: common corporate phrases notably ABSENT. Check for:
  "excited to apply", "passionate about", "results-driven",
  "reach out", "touch base", "circle back", "synergy",
  "leverage" (as verb).
- examples: 5-7 verbatim sentences from the samples that best
  capture the user's voice. Mix of lengths. Prefer sentences that
  show voice, not just content.
- sample_count: honest count of samples provided.

RULES:

1. signature_patterns must be verbatim from samples. Do not paraphrase.

2. If fewer than 3 samples provided, set all confidence-sensitive
   fields conservatively and note sample_count honestly. Downstream
   generators will use this as a directional hint only.

3. Never extract political, personal, or identifying details into
   signature_patterns. Style only.

4. If the samples are short messages only (<50 words total), signal
   low_confidence_reason: "insufficient sample length".

OUTPUT: Valid JSON matching WritingStyleProfile.
"""


async def extract(
    user_id: str,
    samples: list[str],
    session_id: Optional[str] = None,
) -> WritingStyleProfile:
    user_input = json.dumps(
        {
            "sample_count": len(samples),
            "samples": samples,
        },
        default=str,
    )

    profile_id = str(uuid.uuid4())
    now = datetime.utcnow()

    raw = await call_agent(
        agent_name="style_extractor",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=WritingStyleProfile,
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
    )

    # Patch immutable fields not set by LLM
    return raw.model_copy(
        update={
            "profile_id": profile_id,
            "user_id": user_id,
            "source_sample_ids": [],
            "sample_count": len(samples),
            "created_at": now,
            "updated_at": now,
        }
    )
