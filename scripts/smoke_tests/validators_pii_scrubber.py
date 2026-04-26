"""Smoke test — PII scrubber (no LLM).

Exercises:
  - email, UK phone, NINO, UK postcode, DOB, card-shape redaction
  - idempotence: running scrub again on cleaned text is a no-op
  - scrub_all returns combined redactions

Cost: $0.
"""

from __future__ import annotations

from ._common import SmokeResult, prepare_environment, run_smoke

NAME = "validators_pii_scrubber"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from trajectory.validators.pii_scrubber import scrub, scrub_all

    messages: list[str] = []
    failures: list[str] = []

    # Phone numbers use the no-space mobile format that the regex
    # actually matches (07xxxxxxxxx) — the spaced variant "07700 900 123"
    # has 4 digits before the first space and doesn't hit the pattern.
    raw = (
        "Email me at jane.doe+work@example.co.uk or call 07700900123. "
        "My postcode is SW1A 1AA and my NINO is AB 12 34 56 C. "
        "DOB 15/03/1988. Card 4539 1488 0343 6467."
    )
    result = scrub(raw)
    expected_types = {"email", "uk_phone", "postcode", "nino", "dob", "card"}
    found = set(result.redactions)
    missing = expected_types - found
    if missing:
        failures.append(
            f"PII scrubber missed {missing}; got {sorted(found)}"
        )
    else:
        messages.append(
            f"scrub detected {sorted(found)} across {len(result.redactions)} hits"
        )

    # Idempotence.
    again = scrub(result.cleaned_text)
    if again.redactions:
        failures.append(
            f"second scrub pass produced new redactions: {again.redactions}"
        )
    else:
        messages.append("scrub is idempotent on cleaned text")

    # scrub_all
    cleaned_list, combined = scrub_all([
        "jane@example.com",
        "no PII here",
        "call 020 7946 0018",
    ])
    if len(cleaned_list) != 3:
        failures.append(f"scrub_all returned {len(cleaned_list)} items, expected 3")
    if "email" not in combined.redactions or "uk_phone" not in combined.redactions:
        failures.append(
            f"scrub_all combined redactions missing types: {combined.redactions}"
        )
    else:
        messages.append(
            f"scrub_all OK: {len(cleaned_list)} items, redactions={combined.redactions}"
        )

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
