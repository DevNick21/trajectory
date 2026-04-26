"""Smoke test — style_extractor.extract against three short samples.

Exercises the PII scrubber + Tier 1 shield + Opus 4.7 style extraction
pipeline end-to-end. Asserts the LLM-only subschema populated the
WritingStyleProfile and sample_count matches what we passed in.

Set SMOKE_STYLE_EXTRACTOR_MOCK=1 to skip the Opus call.

Cost: ~$0.10 live, $0 mock.
"""

from __future__ import annotations

import os

from ._common import (
    SmokeResult,
    build_synthetic_writing_style,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "style_extractor"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.10


_SAMPLES = [
    "I don't love vague feedback, so I try to leave concrete ones. "
    "When I reviewed the payments PR last week I noted specific lines "
    "and asked whether we had tested the race between the two writers.",
    "We cut p99 latency from 600ms to 195ms across three changes: "
    "parallel validators, an LRU cache for FX rates, and a larger "
    "connection pool. The cache was the riskiest change — we accepted "
    "up to five minutes of staleness on non-FX-sensitive paths.",
    "My inbox tone is plain and short. I don't open with pleasantries. "
    "If I'm unsure I say I'm unsure, and I flag what would change my mind.",
]


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    mock = os.getenv("SMOKE_STYLE_EXTRACTOR_MOCK", "").lower() in {"1", "true", "yes"}
    if not mock:
        missing = require_anthropic_key()
        if missing:
            return [], [missing], 0.0

    messages: list[str] = []
    failures: list[str] = []

    if mock:
        profile = build_synthetic_writing_style("smoke_style_user", sample_count=3)
        messages.append(
            f"MOCK: synthetic profile tone={profile.tone!r} "
            f"formality={profile.formality_level}/10 "
            f"signatures={len(profile.signature_patterns)}"
        )
        return messages, failures, 0.0

    from trajectory.sub_agents import style_extractor

    try:
        profile = await style_extractor.extract(
            user_id="smoke_style_user",
            samples=_SAMPLES,
            session_id="smoke-style",
        )
    except Exception as exc:
        failures.append(f"style_extractor.extract raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"profile tone={profile.tone!r} formality={profile.formality_level}/10 "
        f"hedging={profile.hedging_tendency} samples={profile.sample_count}"
    )
    if profile.sample_count != len(_SAMPLES):
        failures.append(
            f"sample_count mismatch: got {profile.sample_count}, "
            f"expected {len(_SAMPLES)}"
        )
    if not profile.signature_patterns:
        failures.append("no signature_patterns returned.")
    if not profile.avoided_patterns:
        failures.append("no avoided_patterns returned.")

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
