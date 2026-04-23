"""Banned-phrase detection.

The self-audit agent calls `contains_banned` on every Phase 4 generation.
The banned list is authoritative in CLAUDE.md. Additions require a test
case.

The company-swap check is handled by the self-audit LLM itself — a
purely heuristic version previously lived here and got removed because
it false-flagged technical prose lacking proper nouns.
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
