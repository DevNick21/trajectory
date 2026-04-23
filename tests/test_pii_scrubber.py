"""Unit tests for validators/pii_scrubber.py.

Covers positive (PII gets redacted) + negative (benign text untouched)
cases for each category, plus idempotence.
"""

from __future__ import annotations

import pytest

from trajectory.validators.pii_scrubber import scrub, scrub_all


# ---------------------------------------------------------------------------
# Positive: PII is redacted
# ---------------------------------------------------------------------------


_POSITIVE_CASES: dict[str, str] = {
    "email": "Ping me at jane.doe+work@example.co.uk next week.",
    "nino": "My NINO is AB 12 34 56 C for reference.",
    "postcode": "I live in SW1A 1AA, near Westminster.",
    "uk_phone_mobile": "Call me on 07712 345678 after 6pm.",
    "uk_phone_international": "You can reach me at +44 7712 345678.",
    "uk_phone_landline": "Our office line is 020 7946 0958.",
    "card": "Card number 4111 1111 1111 1111 expires 12/27.",
    "dob": "I was born on 15/03/1995 in Glasgow.",
}


@pytest.mark.parametrize("name, text", sorted(_POSITIVE_CASES.items()))
def test_positive_case_redacts(name: str, text: str) -> None:
    result = scrub(text)
    assert result.was_scrubbed, (
        f"Expected PII ({name}) in {text!r} to be redacted; nothing changed."
    )
    assert "[REDACTED:" in result.cleaned_text, (
        f"Expected [REDACTED:…] marker in output; got {result.cleaned_text!r}"
    )


# ---------------------------------------------------------------------------
# Negative: legitimate prose that could trip naive patterns
# ---------------------------------------------------------------------------


_NEGATIVE_CASES: list[str] = [
    "I shipped a feature that cut latency by 40%.",
    "Our team of 12 engineers ships daily.",
    "The release in 2025 was our biggest year.",
    "She earned £75,000 last year.",
    "Order reference 98765 is pending review.",
    "Published in volume 14, issue 3, pages 221-245.",
]


@pytest.mark.parametrize("text", _NEGATIVE_CASES)
def test_negative_case_untouched(text: str) -> None:
    result = scrub(text)
    assert not result.was_scrubbed, (
        f"Benign text {text!r} was redacted unexpectedly: "
        f"{result.cleaned_text!r} (categories: {result.redactions})"
    )
    assert result.cleaned_text == text


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


def test_idempotent() -> None:
    text = "Email me at foo@bar.com or call 07712 345678."
    once = scrub(text).cleaned_text
    twice = scrub(once).cleaned_text
    assert once == twice, "Running scrub twice should be a no-op"


def test_empty_string() -> None:
    result = scrub("")
    assert result.cleaned_text == ""
    assert result.redactions == []


def test_multiple_items_in_one_string() -> None:
    text = (
        "Reach me at jane@example.com or on 07712 345678, "
        "I'm at SW1A 1AA."
    )
    result = scrub(text)
    assert len(result.redactions) == 3
    assert set(result.redactions) == {"email", "uk_phone", "postcode"}


def test_scrub_all_aggregates() -> None:
    samples = [
        "Hi, I'm Jane at jane@example.com.",
        "Just normal prose here about my work.",
        "Call me on 07712 345678 about the role.",
    ]
    cleaned, combined = scrub_all(samples)
    assert len(cleaned) == 3
    assert combined.was_scrubbed
    assert set(combined.redactions) == {"email", "uk_phone"}
