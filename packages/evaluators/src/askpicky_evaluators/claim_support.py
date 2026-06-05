"""Deterministic claim-support checks for generated application answers."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol

from pydantic import BaseModel, Field


class EvidenceItem(Protocol):
    memory_id: str
    text: str


class ClaimSupportResult(BaseModel):
    claim: str
    status: str
    supporting_memory_ids: list[str] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)
    warning: str | None = None


_WORD_RE = re.compile(r"[A-Za-z0-9+#.-]{3,}")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "because",
    "before",
    "but",
    "can",
    "for",
    "from",
    "have",
    "into",
    "that",
    "the",
    "this",
    "through",
    "with",
    "would",
    "your",
}


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _WORD_RE.findall(text)
        if token.lower() not in _STOPWORDS
    }


def _claims(answer: str) -> list[str]:
    raw = [part.strip() for part in _SENTENCE_RE.split(answer.strip())]
    return [part for part in raw if len(_tokens(part)) >= 3]


def evaluate_answer_claim_support(
    *,
    final_answer: str,
    memory_suggestions: Iterable[EvidenceItem],
) -> list[ClaimSupportResult]:
    """Classify answer sentences against selected memory/advice evidence."""

    evidence = list(memory_suggestions)
    indexed = [(item, _tokens(item.text)) for item in evidence]
    results: list[ClaimSupportResult] = []

    for claim in _claims(final_answer):
        claim_tokens = _tokens(claim)
        matches: list[tuple[EvidenceItem, float]] = []
        for item, item_tokens in indexed:
            if not item_tokens:
                continue
            overlap = claim_tokens & item_tokens
            score = len(overlap) / max(len(claim_tokens), 1)
            if score >= 0.2:
                matches.append((item, score))

        matches.sort(key=lambda pair: pair[1], reverse=True)
        best_score = matches[0][1] if matches else 0.0
        if best_score >= 0.45:
            status = "supported"
            warning = None
        elif best_score >= 0.2:
            status = "partially_supported"
            warning = "This claim has partial evidence; review before submitting."
        else:
            status = "unsupported"
            warning = "No selected memory clearly supports this claim."

        results.append(
            ClaimSupportResult(
                claim=claim,
                status=status,
                supporting_memory_ids=[item.memory_id for item, _ in matches[:3]],
                supporting_evidence=[item.text for item, _ in matches[:3]],
                warning=warning,
            )
        )

    return results
