"""API-layer Pydantic models — request bodies + response envelopes.

Distinct from `askpicky.schemas` (the canonical domain models). This
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

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class ForwardJobRequest(BaseModel):
    """POST /api/sessions/forward_job body."""

    job_url: HttpUrl


class QueueAddRequest(BaseModel):
    """POST /api/queue body — accepts one or many URLs at once.

    At least one of the two fields must be non-empty; the endpoint
    rejects empty payloads with 400 so the frontend can keep the
    paste-box input trivial.
    """

    job_url: Optional[HttpUrl] = None
    job_urls: Optional[list[HttpUrl]] = None


class QueueItem(BaseModel):
    """Row in GET /api/queue. Wraps askpicky.schemas.QueuedJob for
    the HTTP layer so the response shape stays stable if the domain
    model grows fields we don't want to expose."""

    id: str
    job_url: str
    status: Literal["pending", "processing", "done", "failed"]
    session_id: Optional[str] = None
    error: Optional[str] = None
    added_at: datetime
    processed_at: Optional[datetime] = None


class QueueListResponse(BaseModel):
    items: list[QueueItem] = Field(default_factory=list)
    pending_count: int = 0
    processing_count: int = 0
    done_count: int = 0
    failed_count: int = 0


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
    verdict: Optional[str] = None  # VerdictLabel string — see trajector/schemas.py
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

    `progress_events` contains the durable event log from
    session_progress_events — empty for pre-migration sessions.
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
    progress_events: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pack generation (Wave 5)
# ---------------------------------------------------------------------------


PackGeneratorName = Literal["cv", "cover_letter", "questions", "salary"]


class PackResult(BaseModel):
    """Response shape for the four individual pack endpoints.

    `output` is the agent's Pydantic output (CVOutput, CoverLetterOutput,
    LikelyQuestionsOutput, SalaryRecommendation) serialised via
    `.model_dump(mode="json")`. `generated_files` lists the rendered
    files (CV + cover letter only — questions + salary live in chat
    payloads with no file deliverables).
    """

    generator: PackGeneratorName
    output: dict[str, Any]
    generated_files: list[GeneratedFile] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Onboarding (Wave 9)
# ---------------------------------------------------------------------------


OnboardingParseStage = Literal[
    "career",
    "motivations",
    "deal_breakers",
    "money",
    "visa",
    "life",
]


class OnboardingParseRequest(BaseModel):
    """Helper for the wizard when it wants to show the user a parsed
    summary before accepting their free-text answer. Finalise does not
    call this; it is exposed only for future per-stage clarification UX."""

    stage: OnboardingParseStage
    text: str


class OnboardingFinaliseRequest(BaseModel):
    """Web wizard's fully-typed payload.

    Structured stages are pre-validated by the frontend. Motivation and
    deal-breaker prose is split deterministically into retrievable preferences.
    Writing-sample onboarding was removed; V2 style guidance comes from
    explicit voice/persona settings and the browser companion feedback loop.
    """

    # Structured fields — no parser needed.
    name: str
    user_type: Literal["visa_holder", "uk_resident"]
    visa_route: Optional[
        Literal["graduate", "skilled_worker", "dependant", "student",
                "global_talent", "other"]
    ] = None
    visa_expiry: Optional[date] = None
    nationality: Optional[str] = None
    base_location: str
    salary_floor: int = Field(ge=0, le=10_000_000)
    salary_target: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    current_employment: Literal["EMPLOYED", "UNEMPLOYED", "NOTICE_PERIOD"]
    search_duration_months: Optional[int] = Field(default=None, ge=0, le=240)

    # Free-text stages — parser runs server-side at finalise time.
    # Empty list is valid (user skipped the stage).
    motivations_text: str = ""
    deal_breakers_text: str = ""
    good_role_signals_text: str = ""  # optional — if given, added separately
    life_constraints: list[str] = Field(default_factory=list)

    # Optional career narrative — stored as a single conversation entry
    # so Phase 4 generators can retrieve it.
    career_narrative: str = ""


class OnboardingFinaliseResponse(BaseModel):
    user_id: str
    career_entries_written: int
