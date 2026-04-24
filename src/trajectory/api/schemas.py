"""API-layer Pydantic models — request bodies + response envelopes.

Distinct from `trajectory.schemas` (the canonical domain models). This
module shapes only what the HTTP layer needs:
  - slim list-item summaries (avoid sending full ResearchBundle in
    list responses)
  - generated-file metadata (filename + size + kind)
  - cost summary

Domain models (`UserProfile`, `Verdict`, `ResearchBundle`,
`ExtractedJobDescription`, etc.) are passed through verbatim where
they're already shaped right.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class SessionSummary(BaseModel):
    """One row in the dashboard's recent-sessions list. Slim by design —
    full detail comes from `GET /api/sessions/{id}`."""

    id: str
    job_url: Optional[str] = None
    intent: str
    created_at: datetime
    verdict: Optional[Literal["GO", "NO_GO"]] = None
    role_title: Optional[str] = None
    company_name: Optional[str] = None


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary] = Field(default_factory=list)


class GeneratedFile(BaseModel):
    filename: str
    size_bytes: int
    kind: Literal["docx", "pdf", "latex_pdf", "other"]
    download_url: str


class CostSummary(BaseModel):
    total_usd: float = 0.0
    by_agent: dict[str, float] = Field(default_factory=dict)


class SessionDetailResponse(BaseModel):
    """Full session payload for the detail page.

    `research_bundle` and `verdict` are passed through as raw dicts so
    the API layer doesn't have to keep its types lockstep with every
    domain-schema tweak. Frontend reads with TanStack Query and types
    against the migration plan's TypeScript shapes.
    """

    id: str
    user_id: str
    job_url: Optional[str] = None
    intent: str
    created_at: datetime
    research_bundle: Optional[dict[str, Any]] = None
    verdict: Optional[dict[str, Any]] = None
    generated_files: list[GeneratedFile] = Field(default_factory=list)
    cost_summary: CostSummary = Field(default_factory=CostSummary)
