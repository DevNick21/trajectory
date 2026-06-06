"""Fast local job-description analysis for first-session value."""

from __future__ import annotations

import re
from typing import Literal

from askpicky_core import (
    ApplicationPriority,
    EvidenceCheckpoint,
    HardFilter,
    LocalJobAnalysis,
)

_SKILLS = [
    "python",
    "typescript",
    "javascript",
    "react",
    "node",
    "fastapi",
    "django",
    "flask",
    "sql",
    "postgres",
    "aws",
    "azure",
    "gcp",
    "docker",
    "kubernetes",
    "terraform",
    "nlp",
    "machine learning",
    "llm",
    "rag",
    "data engineering",
    "spark",
    "dbt",
]

_FILTER_PATTERNS: list[tuple[str, str, Literal["hard", "check"]]] = [
    ("right to work", r"\bright to work\b[^\n.]*", "hard"),
    ("visa sponsorship", r"\b(?:no|not)\s+(?:visa\s+)?sponsor[^\n.]*|\bsponsorship[^\n.]*", "check"),
    ("security clearance", r"\b(?:security clearance|sc cleared|dv cleared)\b[^\n.]*", "hard"),
    ("location", r"\b(?:must be|based in|commutable to|onsite|on-site)\b[^\n.]*", "check"),
    ("years of experience", r"\b\d+\+?\s+years?[^\n.]*", "check"),
    ("degree", r"\b(?:degree|bachelor|masters|phd)\b[^\n.]*", "check"),
]


def _normalise_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _role_title(jd_text: str) -> str:
    for line in jd_text.splitlines():
        cleaned = line.strip(" -|:\t")
        if len(cleaned) >= 4:
            return cleaned[:120]
    return "Unspecified role"


def _skills(jd_text: str) -> list[str]:
    lowered = jd_text.lower()
    found = []
    for skill in _SKILLS:
        if re.search(rf"\b{re.escape(skill)}\b", lowered):
            found.append(skill)
    return found


def _hard_filters(jd_text: str) -> list[HardFilter]:
    filters: list[HardFilter] = []
    for label, pattern, severity in _FILTER_PATTERNS:
        for match in re.finditer(pattern, jd_text, flags=re.IGNORECASE):
            evidence = _normalise_space(match.group(0))
            if evidence and all(existing.evidence != evidence for existing in filters):
                filters.append(HardFilter(label=label, evidence=evidence, severity=severity))
    return filters[:8]


def _role_breakdown(text: str, skills: list[str], filters: list[HardFilter]) -> list[str]:
    breakdown = [f"Role title: {_role_title(text)}"]
    if skills:
        breakdown.append(f"Named skills/tools: {', '.join(skills[:8])}")
    if filters:
        hard = [item.label for item in filters if item.severity == "hard"]
        checks = [item.label for item in filters if item.severity == "check"]
        if hard:
            breakdown.append(f"Hard filters detected: {', '.join(dict.fromkeys(hard))}")
        if checks:
            breakdown.append(f"Filters to confirm: {', '.join(dict.fromkeys(checks))}")
    if "remote" in text.lower() or "hybrid" in text.lower() or "onsite" in text.lower():
        breakdown.append("Working pattern has explicit location or remote-policy language.")
    return breakdown


def _evidence_checkpoints(
    skills: list[str],
    filters: list[HardFilter],
) -> list[EvidenceCheckpoint]:
    checkpoints: list[EvidenceCheckpoint] = []
    for skill in skills[:6]:
        checkpoints.append(
            EvidenceCheckpoint(
                requirement=skill,
                status="needs_profile",
                suggested_evidence=(
                    f"Add a CV bullet, project, or approved memory item that proves {skill}."
                ),
            )
        )
    for item in filters[:4]:
        checkpoints.append(
            EvidenceCheckpoint(
                requirement=item.label,
                status="needs_confirmation",
                suggested_evidence=f"Confirm this requirement before applying: {item.evidence}",
            )
        )
    return checkpoints


def analyse_job_description(jd_text: str) -> LocalJobAnalysis:
    """Return a transparent local analysis for pasted job text."""

    text = jd_text.strip()
    skills = _skills(text)
    filters = _hard_filters(text)
    hard_count = sum(1 for item in filters if item.severity == "hard")

    if hard_count:
        priority: ApplicationPriority = "maybe_apply_after_checking_filters"
    elif len(skills) >= 3:
        priority = "worth_applying_with_tailoring"
    else:
        priority = "low_priority"

    missing = [
        f"Add confirmed evidence for {skill} before claiming it."
        for skill in skills[:6]
    ]
    unsupported = [
        f"Do not claim {skill} experience until it is backed by CV or memory evidence."
        for skill in skills[:6]
    ]
    if filters:
        unsupported.append(
            "Do not imply you clear hard filters until the right-to-work, location, "
            "seniority, or clearance requirement has been confirmed."
        )
    strategy = [
        "Lead with the strongest requirement you can prove from your CV or memory.",
        "Avoid claims that are not backed by confirmed evidence.",
    ]
    if filters:
        strategy.append("Resolve the hard filters before spending time tailoring the application.")
    if skills:
        strategy.append(f"Prioritise evidence for: {', '.join(skills[:5])}.")

    return LocalJobAnalysis(
        role_title=_role_title(text),
        role_breakdown=_role_breakdown(text, skills, filters),
        required_skills=skills,
        hard_filters=filters,
        evidence_checkpoints=_evidence_checkpoints(skills, filters),
        missing_evidence_prompts=missing,
        unsupported_claim_warnings=unsupported,
        application_priority=priority,
        answer_strategy=strategy,
    )
