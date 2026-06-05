"""Compatibility wrapper for the public claim-support evaluator."""

from __future__ import annotations

from collections.abc import Iterable

from askpicky_evaluators import evaluate_answer_claim_support as _evaluate

from ..schemas import GeneratedClaimSupport, MemorySuggestion


def evaluate_answer_claim_support(
    *,
    final_answer: str,
    memory_suggestions: Iterable[MemorySuggestion],
) -> list[GeneratedClaimSupport]:
    """Classify answer sentences against selected memory/advice evidence."""

    return [
        GeneratedClaimSupport(**item.model_dump())
        for item in _evaluate(
            final_answer=final_answer,
            memory_suggestions=memory_suggestions,
        )
    ]
