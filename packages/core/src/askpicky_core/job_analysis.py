"""Shared schema for local job-description analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ApplicationPriority = Literal[
    "worth_applying_with_tailoring",
    "maybe_apply_after_checking_filters",
    "low_priority",
]


class HardFilter(BaseModel):
    label: str
    evidence: str
    severity: Literal["hard", "check"]


class EvidenceCheckpoint(BaseModel):
    requirement: str
    status: Literal["needs_profile", "needs_confirmation"]
    suggested_evidence: str


class LocalJobAnalysis(BaseModel):
    role_title: str
    role_breakdown: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    hard_filters: list[HardFilter] = Field(default_factory=list)
    evidence_checkpoints: list[EvidenceCheckpoint] = Field(default_factory=list)
    missing_evidence_prompts: list[str] = Field(default_factory=list)
    unsupported_claim_warnings: list[str] = Field(default_factory=list)
    application_priority: ApplicationPriority
    answer_strategy: list[str] = Field(default_factory=list)
