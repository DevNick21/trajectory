"""Smoke test — banned-phrase detection (no LLM).

Exercises:
  - Every phrase in BANNED_PHRASES is detected in a crafted sentence.
  - Clean prose passes through with no hits.
  - Word-boundary behaviour (substring matches are NOT flagged).

Cost: $0.
"""

from __future__ import annotations

from ._common import SmokeResult, prepare_environment, run_smoke

NAME = "validators_banned_phrases"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from trajectory.validators.banned_phrases import BANNED_PHRASES, contains_banned

    messages: list[str] = []
    failures: list[str] = []

    # Every banned phrase is caught in a sentence built around it.
    missed: list[str] = []
    for phrase in BANNED_PHRASES:
        sentence = f"I am a {phrase} who ships things."
        hits = contains_banned(sentence)
        if phrase.lower() not in hits:
            missed.append(phrase)
    if missed:
        failures.append(
            f"contains_banned missed {len(missed)} phrase(s): {missed}"
        )
    else:
        messages.append(f"all {len(BANNED_PHRASES)} banned phrases detected")

    # Clean prose: no hits.
    clean = (
        "I shipped a distributed payments pipeline that processed 1M RPS "
        "on Kubernetes and cut tail latency by 400ms."
    )
    hits = contains_banned(clean)
    if hits:
        failures.append(f"clean prose flagged: {hits}")
    else:
        messages.append("clean prose yields no hits")

    # Substring match does NOT trip word boundaries.
    # e.g. "passionately" should NOT flag "passionate" (we use \b\w).
    # The regex uses word boundaries, so "passionately" IS a separate
    # word and won't match — check that substring attacks are bounded.
    sub = "I was dynamically compiling synergized passionately."
    hits = contains_banned(sub)
    # NB — "dynamically" contains "dynamic" but word-boundary should
    # exclude it. "passionately" similarly excludes "passionate".
    if "dynamic" in hits:
        failures.append(
            "word-boundary regex flagged 'dynamic' inside 'dynamically'"
        )
    if "passionate" in hits:
        failures.append(
            "word-boundary regex flagged 'passionate' inside 'passionately'"
        )
    messages.append(f"word-boundary check: hits={hits}")

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
