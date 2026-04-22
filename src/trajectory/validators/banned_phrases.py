"""Banned-phrase detection + company-swap test.

The self-audit agent calls these on every Phase 4 generation. The banned
list is authoritative in CLAUDE.md. Additions require a test case.
"""

from __future__ import annotations

import re


BANNED_PHRASES: set[str] = {
    "passionate",
    "team player",
    "results-driven",
    "synergy",
    "go-getter",
    "proven track record",
    "rockstar",
    "ninja",
    "thought leader",
    "game-changer",
    "leverage",  # flagged as verb — swap test further filters
    "touch base",
    "circle back",
    "reach out",
    "excited to apply",
    "dynamic",
    "hit the ground running",
    "self-starter",
    "out of the box",
    "move the needle",
    "deep dive",
}


def _word_boundary_pattern(phrase: str) -> re.Pattern[str]:
    # Use word boundaries on the ends; treat hyphen/space inside as literal.
    escaped = re.escape(phrase)
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


_PATTERNS: dict[str, re.Pattern[str]] = {
    p: _word_boundary_pattern(p) for p in BANNED_PHRASES
}


def contains_banned(text: str) -> list[str]:
    """Return the banned phrases found in `text` (lowercased, deduped)."""
    hits: set[str] = set()
    for phrase, pattern in _PATTERNS.items():
        if pattern.search(text):
            hits.add(phrase)
    return sorted(hits)


# ---------------------------------------------------------------------------
# Company-swap test
# ---------------------------------------------------------------------------


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def run_company_swap_test(text: str, company_name: str) -> list[str]:
    """Return sentences that are generic — i.e. swapping the company name
    wouldn't change meaning.

    Heuristic: a sentence passes the swap test (= is generic) if it does NOT
    mention the company name, a concrete product/project name, a specific
    team, a verbatim-looking URL snippet, or a quantified claim (numbers).

    This is intentionally a heuristic — the self-audit LLM does the
    judgement call on flagged sentences.
    """
    if not company_name:
        return []

    flagged: list[str] = []
    company_lower = company_name.lower()
    sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]

    for sentence in sentences:
        lower = sentence.lower()
        has_company = company_lower in lower
        has_number = bool(re.search(r"\b\d", sentence))
        has_proper_noun = bool(re.search(r"\b[A-Z][a-zA-Z]{2,}\b", sentence))
        has_specific_quote = '"' in sentence or "'" in sentence

        is_specific = (
            has_company or has_number or has_specific_quote
            or (has_proper_noun and not _is_only_sentence_start_capitalised(sentence))
        )
        if not is_specific:
            flagged.append(sentence)

    return flagged


def _is_only_sentence_start_capitalised(sentence: str) -> bool:
    """True if the only capitalised word is the first word."""
    words = sentence.split()
    if not words:
        return True
    rest_has_caps = any(re.match(r"[A-Z]", w) for w in words[1:])
    return not rest_has_caps
