# SCHEMAS.md — Pydantic Model Catalogue

> Every Pydantic model in Trajectory, in one place.
> Paste directly into `src/trajectory/schemas.py`.
> Pydantic v2 syntax.

```python
"""
Trajectory — canonical Pydantic schemas.

Every LLM input and output in this project validates against one of
these models. If a schema changes, every call site must update.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


class Citation(BaseModel):
    """Every claim in generated output must carry one of these."""

    kind: Literal["url_snippet", "gov_data", "career_entry"]
    # url_snippet fields
    url: Optional[str] = None
    verbatim_snippet: Optional[str] = None
    # gov_data fields
    data_field: Optional[str] = None   # e.g. "sponsor_register.status"
    data_value: Optional[str] = None
    # career_entry fields
    entry_id: Optional[str] = None

    @field_validator("kind")
    @classmethod
    def kind_has_required_fields(cls, v, info):
        # Cross-field validation happens in citation validator module,
        # not here, to avoid Pydantic ordering issues.
        return v


class VisaStatus(BaseModel):
    route: Literal[
        "graduate",
        "skilled_worker",
        "dependant",
        "student",
        "global_talent",
        "other",
    ]
    expiry_date: date


# ---------------------------------------------------------------------------
# User profile + career store
# ---------------------------------------------------------------------------


class UserProfile(BaseModel):
    user_id: str
    name: str
    user_type: Literal["visa_holder", "uk_resident"]

    # visa_holder only
    visa_status: Optional[VisaStatus] = None
    nationality: Optional[str] = None

    # shared fields
    base_location: str
    salary_floor: int                   # GBP, personal walk-away
    salary_target: Optional[int] = None
    target_soc_codes: list[str] = Field(default_factory=list)
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None

    # captured during onboarding
    motivations: list[str] = Field(default_factory=list)
    deal_breakers: list[str] = Field(default_factory=list)
    good_role_signals: list[str] = Field(default_factory=list)
    life_constraints: list[str] = Field(default_factory=list)

    # job search context (drives urgency computation)
    search_started_date: date
    current_employment: Literal["EMPLOYED", "UNEMPLOYED", "NOTICE_PERIOD"]

    writing_style_profile_id: Optional[str] = None

    created_at: datetime
    updated_at: datetime


class CareerEntry(BaseModel):
    entry_id: str
    user_id: str
    kind: Literal[
        "cv_bullet",
        "qa_answer",
        "star_polish",
        "project_note",
        "preference",
        "motivation",
        "deal_breaker",
        "writing_sample",
        "conversation",
    ]
    raw_text: str
    structured: Optional[dict] = None
    source_session_id: Optional[str] = None
    embedding: Optional[list[float]] = None   # 384-dim, sentence-transformers
    created_at: datetime


class WritingStyleProfile(BaseModel):
    profile_id: str
    user_id: str
    tone: str                            # concrete 3-5 words
    sentence_length_pref: Literal["short", "medium", "varied", "long"]
    formality_level: int = Field(ge=1, le=10)
    hedging_tendency: Literal["direct", "moderate", "diplomatic"]
    signature_patterns: list[str]
    avoided_patterns: list[str]
    examples: list[str]                  # 5-7 verbatim sentences
    source_sample_ids: list[str]
    sample_count: int
    low_confidence_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class JobSearchContext(BaseModel):
    """Computed fresh per salary/verdict request. Not stored."""
    user_id: str
    urgency_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    recent_rejections_count: int       # last 30 days
    time_since_last_offer_days: Optional[int] = None
    months_until_visa_expiry: Optional[int] = None
    applications_in_last_30_days: int
    search_duration_months: int


class Session(BaseModel):
    session_id: str
    user_id: str
    intent: str
    job_url: Optional[str] = None
    phase1_output: Optional[dict] = None
    verdict: Optional["Verdict"] = None
    generated_components: dict = Field(default_factory=dict)
    telegram_messages: list[dict] = Field(default_factory=list)
    created_at: datetime


# ---------------------------------------------------------------------------
# Intent routing
# ---------------------------------------------------------------------------


Intent = Literal[
    "forward_job",
    "draft_cv",
    "draft_cover_letter",
    "predict_questions",
    "salary_advice",
    "draft_reply",
    "full_prep",
    "profile_query",
    "profile_edit",
    "recent",
    "chitchat",
]


class IntentRouterOutput(BaseModel):
    intent: Intent
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    extracted_params: dict = Field(default_factory=dict)
    job_url_ref: Optional[str] = None
    missing_context: bool = False
    blocked_by_verdict: bool = False
    reasoning_brief: str


# ---------------------------------------------------------------------------
# Phase 1 — Research
# ---------------------------------------------------------------------------


class ScrapedPage(BaseModel):
    url: str
    fetched_at: datetime
    title: Optional[str] = None
    text: str                          # cleaned, via trafilatura
    text_hash: str


class CultureClaim(BaseModel):
    claim: str                         # e.g. "We ship to prod every day"
    url: str
    verbatim_snippet: str


class CompanyResearch(BaseModel):
    company_name: str
    company_domain: Optional[str] = None
    scraped_pages: list[ScrapedPage]
    culture_claims: list[CultureClaim] = Field(default_factory=list)
    tech_stack_signals: list[str] = Field(default_factory=list)
    team_size_signals: list[str] = Field(default_factory=list)
    recent_activity_signals: list[str] = Field(default_factory=list)
    posted_salary_bands: list[str] = Field(default_factory=list)
    policies: dict = Field(default_factory=dict)   # remote, sponsorship, etc
    careers_page_url: Optional[str] = None
    not_on_careers_page: bool = False


class ExtractedJobDescription(BaseModel):
    role_title: str
    seniority_signal: Literal[
        "intern", "junior", "mid", "senior", "staff", "principal", "unclear"
    ]
    soc_code_guess: str
    soc_code_reasoning: str            # verbatim JD phrase
    salary_band: Optional[dict] = None   # {min, max, currency, period}
    location: str
    remote_policy: Literal["remote", "hybrid", "onsite", "unspecified"]
    required_years_experience: Optional[int] = None
    required_years_experience_range: Optional[list[int]] = None
    required_skills: list[str]
    posted_date: Optional[date] = None
    posting_platform: Literal[
        "linkedin", "indeed", "glassdoor", "company_site", "other"
    ]
    hiring_manager_named: bool
    hiring_manager_name: Optional[str] = None
    jd_text_full: str
    specificity_signals: list[str]
    vagueness_signals: list[str]


class CompaniesHouseSnapshot(BaseModel):
    company_number: str
    status: Literal[
        "ACTIVE",
        "DISSOLVED",
        "IN_ADMINISTRATION",
        "IN_LIQUIDATION",
        "ACTIVE_CONVERSION",
        "OTHER",
    ]
    company_name_official: str
    sic_codes: list[str]
    incorporation_date: Optional[date] = None
    accounts_overdue: bool
    confirmation_statement_overdue: bool
    last_accounts_date: Optional[date] = None
    no_filings_in_years: int = 0
    resolution_to_wind_up: bool = False
    director_disqualifications: int = 0


class SponsorStatus(BaseModel):
    status: Literal["LISTED", "NOT_LISTED", "B_RATED", "SUSPENDED"]
    matched_name: Optional[str] = None
    rating: Optional[str] = None        # A, B, etc.
    visa_routes: list[str] = Field(default_factory=list)
    last_register_update: Optional[date] = None


class SocCheckResult(BaseModel):
    soc_code: str
    soc_title: str
    on_appendix_skilled_occupations: bool
    going_rate_gbp: Optional[int] = None
    new_entrant_rate_gbp: Optional[int] = None
    offered_salary_gbp: Optional[int] = None
    below_threshold: bool
    shortfall_gbp: Optional[int] = None
    new_entrant_eligible: bool = False


class GhostSignal(BaseModel):
    type: Literal[
        "STALE_POSTING",
        "NOT_ON_CAREERS_PAGE",
        "VAGUE_JD",
        "COMPANY_DISTRESS",
    ]
    evidence: str
    citation: Citation
    severity: Literal["HARD", "SOFT"]


class GhostJobJDScore(BaseModel):
    """Output of the ghost-job JD scorer agent (signal 3)."""
    named_hiring_manager: float = Field(ge=0, le=1)
    specific_duty_bullets: float = Field(ge=0, le=1)
    specific_tech_stack: float = Field(ge=0, le=1)
    specific_team_context: float = Field(ge=0, le=1)
    specific_success_metrics: float = Field(ge=0, le=1)
    specificity_score: float = Field(ge=0, le=5)
    specificity_signals: list[str]
    vagueness_signals: list[str]


class GhostJobAssessment(BaseModel):
    probability: Literal["LIKELY_GHOST", "POSSIBLE_GHOST", "LIKELY_REAL"]
    signals: list[GhostSignal]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    raw_jd_score: GhostJobJDScore
    age_days: Optional[int] = None


class SalarySignals(BaseModel):
    posted_band: Optional[dict] = None
    glassdoor_range: Optional[dict] = None
    levels_fyi_range: Optional[dict] = None
    market_p10: Optional[int] = None
    market_p50: Optional[int] = None
    market_p90: Optional[int] = None
    sources_consulted: list[str]
    data_citations: list[Citation]


class RedFlag(BaseModel):
    type: str
    severity: Literal["HARD", "SOFT"]
    summary: str
    citation: Citation


class RedFlagsReport(BaseModel):
    flags: list[RedFlag]
    checked: bool                      # True even if flags is empty


class ResearchBundle(BaseModel):
    """Everything Phase 1 produces, handed to the verdict agent."""
    session_id: str
    extracted_jd: ExtractedJobDescription
    company_research: CompanyResearch
    companies_house: Optional[CompaniesHouseSnapshot] = None
    sponsor_status: Optional[SponsorStatus] = None      # visa_holder only
    soc_check: Optional[SocCheckResult] = None          # visa_holder only
    ghost_job: GhostJobAssessment
    salary_signals: SalarySignals
    red_flags: RedFlagsReport
    bundle_completed_at: datetime


# ---------------------------------------------------------------------------
# Phase 2 — Verdict
# ---------------------------------------------------------------------------


HardBlockerType = Literal[
    # UK resident + shared
    "LIKELY_GHOST_JOB",
    "COMPANIES_HOUSE_DISSOLVED",
    "COMPANIES_HOUSE_NO_FILINGS",
    "BELOW_PERSONAL_FLOOR",
    "BELOW_MARKET_FLOOR",
    "DEAL_BREAKER_TRIGGERED",
    # Visa holder only
    "NOT_ON_SPONSOR_REGISTER",
    "SPONSOR_B_RATED",
    "SPONSOR_SUSPENDED",
    "SALARY_BELOW_SOC_THRESHOLD",
    "SOC_INELIGIBLE",
]


StretchConcernType = Literal[
    "POSSIBLE_GHOST_JOB",
    "COMPANIES_HOUSE_DISTRESS",
    "MOTIVATION_MISMATCH",
    "EXPERIENCE_GAP",
    "CULTURE_SIGNAL_MISMATCH",
    "NATIONALITY_GRANT_RATE_CONTEXT",
]


class HardBlocker(BaseModel):
    type: HardBlockerType
    detail: str
    citation: Citation


class StretchConcern(BaseModel):
    type: StretchConcernType
    detail: str
    citations: list[Citation]


class ReasoningPoint(BaseModel):
    claim: str
    supporting_evidence: str
    citation: Citation


class Verdict(BaseModel):
    decision: Literal["GO", "NO_GO"]
    confidence_pct: int = Field(ge=0, le=100)
    headline: str                      # <= 12 words
    reasoning: list[ReasoningPoint]
    hard_blockers: list[HardBlocker]
    stretch_concerns: list[StretchConcern]
    motivation_fit: "MotivationFitReport"
    estimated_callback_probability: Optional[
        Literal["LOW", "MEDIUM", "HIGH"]
    ] = None

    @field_validator("headline")
    @classmethod
    def headline_length(cls, v: str) -> str:
        if len(v.split()) > 12:
            raise ValueError(
                f"headline must be <=12 words; got {len(v.split())}: {v!r}"
            )
        return v


class MotivationFitReport(BaseModel):
    motivation_evaluations: list[dict]   # [{motivation, status, citation}]
    deal_breaker_evaluations: list[dict]
    good_role_signal_evaluations: list[dict]


# ---------------------------------------------------------------------------
# Phase 3 — Dialogue
# ---------------------------------------------------------------------------


TargetGap = Literal[
    "TECHNICAL_EVIDENCE",
    "IMPACT_QUANTIFICATION",
    "CULTURE_ALIGNMENT",
    "STRETCH_CONCERN",
    "FRESH_STORY",
]


class DesignedQuestion(BaseModel):
    question_text: str
    rationale: str                     # internal, not shown to user
    target_gap: TargetGap
    required_output_for_pack: str


class QuestionSet(BaseModel):
    questions: list[DesignedQuestion]  # exactly 3


class STARComponent(BaseModel):
    text: str
    confidence: float = Field(ge=0, le=1)


class STARPolish(BaseModel):
    question: str
    raw_answer: str
    situation: STARComponent
    task: STARComponent
    action: STARComponent
    result: STARComponent
    clarifying_question: Optional[str] = None
    overall_confidence: float = Field(ge=0, le=1)


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------


class OnboardingTranscript(BaseModel):
    user_id: str
    topic_answers: dict                 # topic -> user-text
    writing_samples: list[str]


class OnboardingResult(BaseModel):
    profile: UserProfile
    career_entries: list[CareerEntry]   # new entries to create
    writing_style_profile: WritingStyleProfile
    ambiguities_flagged: list[str]      # bot confirms with user


# ---------------------------------------------------------------------------
# Phase 4 — Pack
# ---------------------------------------------------------------------------


class CVBullet(BaseModel):
    text: str
    citations: list[Citation]          # career_entry_id refs + jd_phrase


class CVRole(BaseModel):
    title: str
    company: str
    dates: str
    bullets: list[CVBullet]


class CVOutput(BaseModel):
    name: str
    contact: dict
    professional_summary: str
    experience: list[CVRole]
    education: list[dict]
    skills: list[str]
    projects: Optional[list[dict]] = None


class CoverLetterOutput(BaseModel):
    addressed_to: str
    paragraphs: list[str]              # 3-4 short paragraphs
    citations: list[Citation]
    word_count: int


class LikelyQuestion(BaseModel):
    question: str
    bucket: Literal[
        "technical", "experience", "behavioural", "motivation_fit",
        "commercial_strategic"
    ]
    likelihood: Literal["HIGH", "MEDIUM", "LOW"]
    why_likely: str
    citation: Citation
    strategy_note: str
    relevant_career_entry_ids: list[str]


class LikelyQuestionsOutput(BaseModel):
    questions: list[LikelyQuestion]    # 8-12 total


class SalaryRecommendation(BaseModel):
    opening_number: int                # GBP
    opening_phrasing: str
    floor: int
    ceiling: int
    reasoning: list[ReasoningPoint]
    sponsor_constraint_active: bool
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    scripts: dict                       # keys described in AGENTS.md
    data_gaps: list[str]
    urgency_note: Optional[str] = None


class DraftReplyOutput(BaseModel):
    user_intent_interpreted: Literal[
        "accept_call",
        "decline_politely",
        "ask_for_details",
        "negotiate_salary",
        "defer",
        "other",
    ]
    short_variant: str
    long_variant: str
    citations: list[Citation] = Field(default_factory=list)


class Pack(BaseModel):
    """Aggregate of Phase 4 outputs (populated incrementally by intent)."""
    session_id: str
    cv: Optional[CVOutput] = None
    cover_letter: Optional[CoverLetterOutput] = None
    likely_questions: Optional[LikelyQuestionsOutput] = None
    salary: Optional[SalaryRecommendation] = None


# ---------------------------------------------------------------------------
# Phase 4.5 — Self-Audit
# ---------------------------------------------------------------------------


FlagType = Literal[
    "UNSUPPORTED_CLAIM",
    "CLICHE",
    "HEDGING",
    "COMPANY_SWAP_FAIL",
    "STYLE_MISMATCH",
    "HARD_REJECT",
]


class AuditFlag(BaseModel):
    flag_type: FlagType
    offending_substring: str
    proposed_rewrite: str
    citation: Optional[Citation] = None


class SelfAuditReport(BaseModel):
    flags: list[AuditFlag]
    hard_reject: bool
    overall_style_conformance: int = Field(ge=0, le=10)


# ---------------------------------------------------------------------------
# Resolve forward references
# ---------------------------------------------------------------------------

Session.model_rebuild()
Verdict.model_rebuild()
```

---

## Enum quick-reference

A copy-paste cheat sheet for common enum values used across prompts:

| Enum | Values |
|------|--------|
| `Intent` | `forward_job, draft_cv, draft_cover_letter, predict_questions, salary_advice, draft_reply, full_prep, profile_query, profile_edit, recent, chitchat` |
| `HardBlockerType` | See model. 11 values. |
| `StretchConcernType` | See model. 6 values. |
| `GhostSignal.type` | `STALE_POSTING, NOT_ON_CAREERS_PAGE, VAGUE_JD, COMPANY_DISTRESS` |
| `UserType` | `visa_holder, uk_resident` |
| `Employment` | `EMPLOYED, UNEMPLOYED, NOTICE_PERIOD` |
| `Urgency` | `LOW, MEDIUM, HIGH, CRITICAL` |

---

## When schemas change

If a schema adds a new field:

1. Update this file.
2. Update `AGENTS.md` entry for any affected agent (prompts reference exact field names).
3. Update the call site that produces the value.
4. Update the call site that consumes the value.
5. If the new field is required, bump an internal version marker and verify the orchestrator handles both versions gracefully mid-session.

If a schema removes a field: never in the middle of the hackathon. Deprecate, then remove post-submission.
