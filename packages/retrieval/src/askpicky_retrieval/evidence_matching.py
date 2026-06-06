"""Deterministic local requirement-to-evidence matching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from askpicky_core import EvidenceCheckpoint, LocalJobAnalysis


@dataclass(frozen=True)
class EvidenceDocument:
    evidence_id: str
    text: str
    structured_text: str = ""

    @property
    def search_text(self) -> str:
        return f"{self.text} {self.structured_text}".lower()


def _requirement_aliases(requirement: str) -> list[str]:
    lowered = requirement.lower().strip()
    aliases: dict[str, list[str]] = {
        "sql": ["sql", "postgresql", "postgres", "mysql", "sqlite"],
        "postgres": ["postgres", "postgresql"],
        "javascript": ["javascript", "js"],
        "typescript": ["typescript", "ts"],
        "machine learning": ["machine learning", "ml"],
        "llm": ["llm", "large language model", "language model"],
        "rag": [
            "rag",
            "retrieval augmented generation",
            "retrieval-augmented generation",
        ],
        "data engineering": ["data engineering", "data pipelines", "etl"],
    }
    return [lowered, *aliases.get(lowered, [])]


def _matches_requirement(requirement: str, text: str) -> bool:
    for alias in _requirement_aliases(requirement):
        if len(alias) <= 3:
            if re.search(rf"\b{re.escape(alias)}\b", text):
                return True
        elif alias in text:
            return True
    return False


def _supporting_document(
    requirement: str,
    documents: list[EvidenceDocument],
) -> Optional[EvidenceDocument]:
    for document in documents:
        if _matches_requirement(requirement, document.search_text):
            return document
    return None


def _snippet(text: str, limit: int = 220) -> str:
    cleaned = text.strip().replace("\n", " ")
    if len(cleaned) > limit:
        return f"{cleaned[:limit - 3]}..."
    return cleaned


def build_evidence_snapshot(
    analysis: LocalJobAnalysis,
    documents: list[EvidenceDocument],
) -> LocalJobAnalysis:
    """Refresh claim-support states from saved local evidence."""

    checkpoints: list[EvidenceCheckpoint] = []
    for checkpoint in analysis.evidence_checkpoints:
        if checkpoint.status == "needs_confirmation":
            checkpoints.append(checkpoint)
            continue

        supporting = _supporting_document(checkpoint.requirement, documents)
        if supporting is not None:
            checkpoints.append(
                EvidenceCheckpoint(
                    requirement=checkpoint.requirement,
                    status="matched",
                    suggested_evidence=(
                        f"Matched career evidence {supporting.evidence_id}: "
                        f"{_snippet(supporting.text)}"
                    ),
                )
            )
        elif documents:
            checkpoints.append(
                EvidenceCheckpoint(
                    requirement=checkpoint.requirement,
                    status="missing",
                    suggested_evidence=(
                        "No saved CV/profile evidence matches this requirement yet. "
                        "Add or approve evidence before using this claim."
                    ),
                )
            )
        else:
            checkpoints.append(
                EvidenceCheckpoint(
                    requirement=checkpoint.requirement,
                    status="needs_profile",
                    suggested_evidence=checkpoint.suggested_evidence,
                )
            )

    missing_requirements = [
        item.requirement
        for item in checkpoints
        if item.status in {"missing", "needs_profile"}
    ]
    missing_prompts = [
        f"Add confirmed evidence for {requirement} before claiming it."
        for requirement in missing_requirements
    ]
    unsupported = [
        f"Do not claim {requirement} experience until it is backed by CV or memory evidence."
        for requirement in missing_requirements
    ]
    if any(item.status == "needs_confirmation" for item in checkpoints):
        unsupported.append(
            "Do not imply you clear hard filters until the right-to-work, "
            "location, seniority, or clearance requirement has been confirmed."
        )

    return analysis.model_copy(
        update={
            "evidence_checkpoints": checkpoints,
            "missing_evidence_prompts": missing_prompts,
            "unsupported_claim_warnings": unsupported,
        }
    )
