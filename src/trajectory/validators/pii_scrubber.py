"""PII scrubber for onboarding writing samples.

Runs BEFORE user text reaches an LLM that synthesises new text from it
(primarily `style_extractor`, which is Opus 4.7 xhigh). The goal is to
prevent a user's email address, phone number, National Insurance number,
postcode, or card number from being pickled into a WritingStyleProfile
that then gets cited in cover letters.

Complements `validators/content_shield.py`:
  - Content Shield strips prompt-injection patterns (role-switch,
    "ignore previous instructions", etc.)
  - PII scrubber strips personal identifiers the user may have
    left in writing samples.

Both run on untrusted inputs. They're separate because the failure
modes are different — one is about agent behaviour, one is about data
leakage into generated output.

Name detection is intentionally NOT here — accurate name NER requires
a real model, and false-positives ("Monday" as a first name, "London"
as a last name) would shred legitimate writing samples. The downstream
banned-phrases / self-audit loop catches the edge cases.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------
#
# Each tuple is (pattern_name, regex, replacement). The regex is
# compiled once at module load. Replacements include the pattern name
# so downstream readers can tell WHY a chunk of text was redacted.


# Email — RFC 5322 simplified. Covers john.doe+work@example.co.uk.
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# UK National Insurance number (2 letters, 6 digits, 1 letter).
# Letters D, F, I, Q, U, V are disallowed in the prefix; O is allowed
# only in second position. Our pattern is slightly broad but the NINO
# structure is distinctive enough that false-positives are rare.
_NINO_RE = re.compile(
    r"\b[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b"
)

# UK postcode — covers "SW1A 1AA", "EC2V 7RR", "BT1 1AA" (NI), "GIR 0AA".
_POSTCODE_RE = re.compile(
    r"\b(?:GIR\s?0AA|[A-PR-UWYZ][A-HK-Y]?\d[A-Z\d]?\s?\d[ABD-HJLNP-UW-Z]{2})\b",
    re.IGNORECASE,
)

# UK phone numbers.
# - International (+44 / 0044) followed by 10 or 11 digits
# - Domestic 07xxx xxxxxx mobile
# - Domestic 01/02/03 landlines
# We require either a leading non-digit or line start to avoid catching
# numbers inside longer digit strings (e.g. account references).
_UK_PHONE_RE = re.compile(
    r"(?:(?<!\d)(?:\+44\s?|0044\s?|0))"
    r"(?:7\d{3}\s?\d{6}"                # mobile 07xxx xxxxxx
    r"|[12389]\d\s?\d{4}\s?\d{4}"       # 01/02/03/08/09 landlines
    r"|[12389]\d{9})"                   # unspaced landline/mobile
    r"(?!\d)"
)

# Credit-card-like 13-19 digit blocks with optional space / hyphen
# grouping. Matches on the visible format rather than Luhn-validating —
# false positives on "order number 1234 5678 9012 3456" are acceptable
# (redacting an order number harms nothing).
_CARD_RE = re.compile(
    r"\b(?:\d[ -]?){12,18}\d\b"
)

# Date of birth — common written forms. Keep this narrow so normal
# sentences with dates ("posted 15/3/2025") aren't redacted unless
# they look distinctly birth-date-shaped (DD/MM/YYYY or DD MMM YYYY).
# We redact anything written as DD/MM/YYYY because downstream we can't
# tell a DOB from a random date; users can opt to paste fewer dates.
_DOB_RE = re.compile(
    r"\b(?:0[1-9]|[12]\d|3[01])[/\- ](?:0[1-9]|1[0-2])[/\- ](?:19|20)\d{2}\b"
)


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", _EMAIL_RE),
    ("nino", _NINO_RE),
    ("postcode", _POSTCODE_RE),
    ("uk_phone", _UK_PHONE_RE),
    ("card", _CARD_RE),
    ("dob", _DOB_RE),
)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@dataclass
class ScrubResult:
    cleaned_text: str
    redactions: list[str] = field(default_factory=list)

    @property
    def was_scrubbed(self) -> bool:
        return bool(self.redactions)

    def summary(self) -> str:
        if not self.redactions:
            return "no PII detected"
        counts: dict[str, int] = {}
        for r in self.redactions:
            counts[r] = counts.get(r, 0) + 1
        return ", ".join(f"{name}={n}" for name, n in sorted(counts.items()))


def scrub(text: str) -> ScrubResult:
    """Return `text` with PII replaced by `[REDACTED: <type>]` markers.

    Idempotent — running on already-scrubbed text is a no-op since the
    `[REDACTED: ...]` markers don't match any of the patterns.
    """
    if not text:
        return ScrubResult(cleaned_text="")

    cleaned = text
    redactions: list[str] = []
    for name, regex in _PATTERNS:
        def _replace(match: re.Match[str], _name: str = name) -> str:
            redactions.append(_name)
            return f"[REDACTED: {_name}]"
        cleaned = regex.sub(_replace, cleaned)

    if redactions:
        logger.info("PII scrubber redacted %d item(s): %s",
                    len(redactions),
                    ", ".join(sorted(set(redactions))))
    return ScrubResult(cleaned_text=cleaned, redactions=redactions)


def scrub_all(texts: list[str]) -> tuple[list[str], ScrubResult]:
    """Scrub a list of samples. Returns (cleaned_list, combined_result).

    Useful for the style_extractor entry point where we want one log
    line per onboarding run rather than per sample.
    """
    cleaned: list[str] = []
    combined = ScrubResult(cleaned_text="")
    for t in texts:
        r = scrub(t)
        cleaned.append(r.cleaned_text)
        combined.redactions.extend(r.redactions)
    combined.cleaned_text = "\n\n".join(cleaned)
    return cleaned, combined
