"""
Trajectory — canonical Pydantic schemas.

Every LLM input and output in this project validates against one of
these models. If a schema changes, every call site must update.

Source of truth: SCHEMAS.md.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


# Phase 1 sub-agents each return a typed payload. When the upstream call
# fails (timeout, API 500, connection error), we still return a valid
# payload shape so `asyncio.gather(return_exceptions=False)` completes —
# but the verdict agent needs to know the difference between "no data"
# (genuine miss) and "unreachable" (we couldn't look). See AGENTS.md
# and orchestrator.py's run_* wrappers. "STALE" is reserved for gov
# data older than the freshness window (see scripts/fetch_gov_data.py).
SourceStatus = Literal["OK", "UNREACHABLE", "NO_DATA", "STALE"]


class Citation(BaseModel):
    """Every claim in generated output must carry one of these."""

    kind: Literal["url_snippet", "gov_data", "career_entry"]
    # url_snippet fields
    url: Optional[str] = None
    verbatim_snippet: Optional[str] = None
    # gov_data fields
    data_field: Optional[str] = None
    data_value: Optional[str] = None
    # career_entry fields
    entry_id: Optional[str] = None

    @model_validator(mode="after")
    def _kind_requires_its_fields(self) -> "Citation":
        # Enforce at schema level that the per-kind required fields are
        # present. Deeper resolution (does the snippet actually exist in
        # the scraped bundle? does the entry_id exist in the career store?)
        # stays in validators/citations.py because it needs runtime state.
        if self.kind == "url_snippet":
            if not self.url or not self.verbatim_snippet:
                raise ValueError(
                    "Citation(kind='url_snippet') requires both url and "
                    "verbatim_snippet to be non-empty."
                )
        elif self.kind == "gov_data":
            # Reject both None and empty-string data_value — an empty value
            # isn't a real citation, and resolving against it would silently
            # match any empty/missing field in the bundle.
            if not self.data_field or not self.data_value:
                raise ValueError(
                    "Citation(kind='gov_data') requires data_field and "
                    "data_value to be non-empty."
                )
        elif self.kind == "career_entry":
            if not self.entry_id:
                raise ValueError(
                    "Citation(kind='career_entry') requires entry_id."
                )
        return self

    # ------------------------------------------------------------------
    # Citations API projector (PROCESS Entry 43, Workstream B)
    # ------------------------------------------------------------------

    @classmethod
    def from_api(
        cls,
        raw: dict,
        *,
        url_by_doc_index: Optional[dict[int, str]] = None,
        kind_by_doc_index: Optional[dict[int, Literal["url_snippet", "gov_data", "career_entry"]]] = None,
        gov_field_by_doc_index: Optional[dict[int, str]] = None,
        entry_id_by_doc_index: Optional[dict[int, str]] = None,
    ) -> "Citation":
        """Project an Anthropic Citations-API citation dict into our domain
        shape.

        The API returns one of three citation kinds:
          - `char_location` (plain-text documents)
          - `page_location` (PDF documents)
          - `content_block_location` (custom-content documents)

        Each carries a `document_index` referencing the originally-supplied
        document. Callers tell us how to interpret each document index via
        the *_by_doc_index dicts:

          - `url_by_doc_index[i] = "https://..."` -> `kind="url_snippet"`
          - `kind_by_doc_index[i] = "gov_data"` + `gov_field_by_doc_index[i]
            = "sponsor_status.status"` -> `kind="gov_data"` with
            `data_value = raw["cited_text"].strip()`
          - `entry_id_by_doc_index[i] = "entry-..."` -> `kind="career_entry"`

        If no mapping covers `raw["document_index"]`, defaults to
        `kind="url_snippet"` with the document_title as the URL — caller
        should always pass at least `url_by_doc_index` to avoid this fallback.
        """
        idx = int(raw.get("document_index", 0))
        cited_text = (raw.get("cited_text") or "").strip()

        # Per-doc-index override is the cleanest path.
        if kind_by_doc_index and idx in kind_by_doc_index:
            kind = kind_by_doc_index[idx]
            if kind == "gov_data":
                if not gov_field_by_doc_index or idx not in gov_field_by_doc_index:
                    raise ValueError(
                        f"document_index {idx} marked gov_data but no "
                        "gov_field_by_doc_index entry present."
                    )
                return cls(
                    kind="gov_data",
                    data_field=gov_field_by_doc_index[idx],
                    data_value=cited_text or "unknown",
                )
            if kind == "career_entry":
                if not entry_id_by_doc_index or idx not in entry_id_by_doc_index:
                    raise ValueError(
                        f"document_index {idx} marked career_entry but no "
                        "entry_id_by_doc_index entry present."
                    )
                return cls(
                    kind="career_entry",
                    entry_id=entry_id_by_doc_index[idx],
                )
            # Otherwise fall through to url_snippet handling.

        # Default: url_snippet.
        url = (url_by_doc_index or {}).get(idx) or raw.get("document_title") or ""
        if not url or not cited_text:
            raise ValueError(
                f"Cannot project citation idx={idx}: missing url or cited_text. "
                f"raw={raw!r}"
            )
        return cls(
            kind="url_snippet",
            url=url,
            verbatim_snippet=cited_text,
        )


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
    salary_floor: int
    salary_target: Optional[int] = None
    target_soc_codes: list[str] = Field(default_factory=list)
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None

    # onboarding-captured
    motivations: list[str] = Field(default_factory=list)
    deal_breakers: list[str] = Field(default_factory=list)
    good_role_signals: list[str] = Field(default_factory=list)
    life_constraints: list[str] = Field(default_factory=list)

    # job search context
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
        "good_role_signal",
        "writing_sample",
        "conversation",
    ]
    raw_text: str
    structured: Optional[dict] = None
    source_session_id: Optional[str] = None
    embedding: Optional[list[float]] = None  # 384-dim
    created_at: datetime


class WritingStyleProfile(BaseModel):
    profile_id: str
    user_id: str
    tone: str
    sentence_length_pref: Literal["short", "medium", "varied", "long"]
    formality_level: int = Field(ge=1, le=10)
    hedging_tendency: Literal["direct", "moderate", "diplomatic"]
    signature_patterns: list[str]
    avoided_patterns: list[str]
    examples: list[str]
    source_sample_ids: list[str]
    sample_count: int
    low_confidence_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class WritingStyleProfileLLMOutput(BaseModel):
    """Subset of WritingStyleProfile that the LLM should actually produce.

    Identity/audit fields (profile_id, user_id, source_sample_ids,
    sample_count, created_at, updated_at) are injected by the caller.
    Having the LLM hallucinate them wastes tokens and invites made-up
    IDs that don't exist in the career store.
    """

    tone: str
    sentence_length_pref: Literal["short", "medium", "varied", "long"]
    formality_level: int = Field(ge=1, le=10)
    hedging_tendency: Literal["direct", "moderate", "diplomatic"]
    signature_patterns: list[str]
    avoided_patterns: list[str]
    examples: list[str]
    low_confidence_reason: Optional[str] = None


class JobSearchContext(BaseModel):
    """Computed fresh per salary/verdict request. Not stored."""

    user_id: str
    urgency_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    recent_rejections_count: int
    time_since_last_offer_days: Optional[int] = None
    months_until_visa_expiry: Optional[int] = None
    applications_in_last_30_days: int
    search_duration_months: int


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
    # New post-2026-04-25 intent (PROCESS Entry 43, Workstream F):
    # user forwards an offer letter PDF; pipeline returns OfferAnalysis.
    "analyse_offer",
    "profile_query",
    "profile_edit",
    "recent",
    "chitchat",
]


# ---------------------------------------------------------------------------
# Offer analysis (PROCESS Entry 43, Workstream F)
# ---------------------------------------------------------------------------


class OfferComponent(BaseModel):
    """A single field extracted from an offer letter, with a citation
    pointing at the page it came from.
    """

    label: str           # e.g. "base salary", "equity vesting", "non-compete"
    value_text: str      # verbatim or normalised value
    citation: "Citation"


class OfferAnalysis(BaseModel):
    """Output of the `analyse_offer` intent.

    Every field is page-cited via the Citations API. The `unusual_clauses`
    bucket flags terms a UK candidate should question (overly long
    non-competes, IP assignment over personal projects, equity acceleration
    cliffs, etc.).
    """

    company_name: str
    role_title: Optional[str] = None
    base_salary_gbp: Optional[OfferComponent] = None
    bonus: Optional[OfferComponent] = None
    equity: Optional[OfferComponent] = None
    benefits: list[OfferComponent] = Field(default_factory=list)
    notice_period: Optional[OfferComponent] = None
    non_compete: Optional[OfferComponent] = None
    ip_assignment: Optional[OfferComponent] = None
    unusual_clauses: list[OfferComponent] = Field(default_factory=list)
    market_comparison_note: Optional[str] = None
    # Surfaced as warnings to the user (e.g. "below SOC threshold for
    # Skilled Worker — sponsor unlikely to support visa").
    flags: list[str] = Field(default_factory=list)


class Session(BaseModel):
    session_id: str
    user_id: str
    intent: Intent
    job_url: Optional[str] = None
    # Persistent Job entity reference (PROCESS Entry 45). The same role
    # at the same company gets one job_id even across multiple URL
    # forwards / re-listings; sessions reference it so the bot can
    # answer "draft me a CV for that role at Acme" by job, not by
    # session-recency.
    job_id: Optional[str] = None
    phase1_output: Optional[dict] = None
    verdict: Optional["Verdict"] = None
    generated_components: dict = Field(default_factory=dict)
    telegram_messages: list[dict] = Field(default_factory=list)
    created_at: datetime


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
    text: str
    text_hash: str


class CultureClaim(BaseModel):
    claim: str
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
    policies: dict = Field(default_factory=dict)
    careers_page_url: Optional[str] = None
    not_on_careers_page: bool = False


class JsonLdExtraction(BaseModel):
    """Fields extracted from a Schema.org JobPosting JSON-LD block.

    Only populated when the source is authoritative Schema.org. Values are
    ground truth — the Sonnet JD extractor should defer to these rather
    than re-inferring from body text. This model is an internal
    intermediate: NOT stored in the research bundle, NOT passed to the
    verdict agent, NOT cited.
    """

    title: Optional[str] = None
    date_posted: Optional[date] = None
    valid_through: Optional[date] = None
    hiring_organization_name: Optional[str] = None
    employment_type: Optional[str] = None
    location: Optional[str] = None
    salary_min_gbp: Optional[int] = None
    salary_max_gbp: Optional[int] = None
    salary_period: Optional[Literal["annual", "hourly", "daily", "monthly"]] = None
    description_plain: Optional[str] = None
    raw_fields_present: list[str] = Field(default_factory=list)


class ExtractedJobDescription(BaseModel):
    role_title: str
    seniority_signal: Literal[
        "intern", "junior", "mid", "senior", "staff", "principal", "unclear"
    ]
    soc_code_guess: str
    soc_code_reasoning: str
    salary_band: Optional[dict] = None
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
    source_status: SourceStatus = "OK"


class SponsorStatus(BaseModel):
    status: Literal[
        "LISTED", "NOT_LISTED", "B_RATED", "SUSPENDED", "UNKNOWN"
    ]
    matched_name: Optional[str] = None
    rating: Optional[str] = None
    visa_routes: list[str] = Field(default_factory=list)
    last_register_update: Optional[date] = None
    source_status: SourceStatus = "OK"


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
    source_status: SourceStatus = "OK"


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


class AshePercentiles(BaseModel):
    granularity: Literal["soc4_region", "soc2_region", "soc2_national"]
    soc_code: str
    region: Optional[str] = None
    p10: Optional[int] = None
    p25: Optional[int] = None
    p50: Optional[int] = None
    p75: Optional[int] = None
    p90: Optional[int] = None
    sample_year: int


class PostedBand(BaseModel):
    min_gbp: int
    max_gbp: int
    period: Literal["annual", "hourly", "daily"]
    source_url: str
    verbatim_snippet: str


class AggregatedPostings(BaseModel):
    listings_count: int
    p25_gbp: Optional[int] = None
    p50_gbp: Optional[int] = None
    p75_gbp: Optional[int] = None
    sample_urls: list[str] = Field(default_factory=list)


class SalarySignals(BaseModel):
    ashe: Optional[AshePercentiles] = None
    posted_band: Optional[PostedBand] = None
    aggregated_postings: Optional[AggregatedPostings] = None
    sources_consulted: list[str]
    data_citations: list[Citation]
    source_status: SourceStatus = "OK"


class RedFlag(BaseModel):
    type: str
    severity: Literal["HARD", "SOFT"]
    summary: str
    citation: Citation


class RedFlagsReport(BaseModel):
    flags: list[RedFlag]
    checked: bool
    source_status: SourceStatus = "OK"


class ResearchBundle(BaseModel):
    """Everything Phase 1 produces, handed to the verdict agent."""

    session_id: str
    extracted_jd: ExtractedJobDescription
    company_research: CompanyResearch
    companies_house: Optional[CompaniesHouseSnapshot] = None
    sponsor_status: Optional[SponsorStatus] = None
    soc_check: Optional[SocCheckResult] = None
    ghost_job: GhostJobAssessment
    salary_signals: SalarySignals
    red_flags: RedFlagsReport
    bundle_completed_at: datetime
    # Names of source fields whose text was truncated by the content
    # shield before reaching downstream agents. Verdict and generators
    # treat a value appearing here as "partial view, reason cautiously."
    # A5 / content_shield.ShieldResult.truncated.
    sources_truncated: list[str] = Field(default_factory=list)


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
    # AGENTS.md §18 — Content Shield Tier 2 returned REJECT or
    # SUSPICIOUS for the bundle backing this verdict. Surfaces as a
    # stretch concern so the user can see why the verdict downgraded.
    "CONTENT_INTEGRITY_CONCERN",
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


class MotivationFitReport(BaseModel):
    motivation_evaluations: list[dict]
    deal_breaker_evaluations: list[dict]
    good_role_signal_evaluations: list[dict]


class Verdict(BaseModel):
    decision: Literal["GO", "NO_GO"]
    confidence_pct: int = Field(ge=0, le=100)
    headline: str  # <= 12 words
    reasoning: list[ReasoningPoint]
    hard_blockers: list[HardBlocker]
    stretch_concerns: list[StretchConcern]
    motivation_fit: MotivationFitReport
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
    rationale: str
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
    topic_answers: dict
    writing_samples: list[str]


class OnboardingResult(BaseModel):
    profile: UserProfile
    career_entries: list[CareerEntry]
    writing_style_profile: WritingStyleProfile
    ambiguities_flagged: list[str]


# ---------------------------------------------------------------------------
# Onboarding parser (per-stage, Opus 4.7 low effort)
#
# Each onboarding stage has its own parse-result schema. The parser agent
# decides whether the user's reply covered enough for that stage to
# advance. If it didn't, `status="needs_clarification"` with a targeted
# `follow_up` question bounces back to the user instead of polluting the
# profile with regex-best-effort guesses.
# ---------------------------------------------------------------------------


_ParseStatus = Literal["parsed", "needs_clarification", "off_topic"]


class _StageParseBase(BaseModel):
    status: _ParseStatus
    follow_up: Optional[str] = None


class CareerParseResult(_StageParseBase):
    narrative: Optional[str] = None
    roles_mentioned: list[str] = Field(default_factory=list)
    years_total: Optional[int] = None


class MotivationsParseResult(_StageParseBase):
    motivations: list[str] = Field(default_factory=list)
    drains: list[str] = Field(default_factory=list)


class MoneyParseResult(_StageParseBase):
    salary_floor_gbp: Optional[int] = None
    salary_target_gbp: Optional[int] = None


class DealBreakersParseResult(_StageParseBase):
    deal_breakers: list[str] = Field(default_factory=list)
    good_role_signals: list[str] = Field(default_factory=list)


class VisaParseResult(_StageParseBase):
    user_type: Optional[Literal["visa_holder", "uk_resident"]] = None
    visa_route: Optional[
        Literal[
            "graduate", "skilled_worker", "dependant",
            "student", "global_talent", "other",
        ]
    ] = None
    visa_expiry: Optional[date] = None
    base_location: Optional[str] = None
    open_to_relocation: Optional[bool] = None


class LifeParseResult(_StageParseBase):
    current_employment: Optional[
        Literal["EMPLOYED", "NOTICE_PERIOD", "UNEMPLOYED"]
    ] = None
    search_duration_months: Optional[int] = None
    hard_deadline: Optional[str] = None


class SamplesParseResult(_StageParseBase):
    samples: list[str] = Field(default_factory=list)
    sample_count: int = 0


# ---------------------------------------------------------------------------
# Phase 4 — Pack
# ---------------------------------------------------------------------------


class CVBullet(BaseModel):
    text: str
    citations: list[Citation]


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
    paragraphs: list[str]
    citations: list[Citation]
    word_count: int


class LikelyQuestion(BaseModel):
    question: str
    bucket: Literal[
        "technical",
        "experience",
        "behavioural",
        "motivation_fit",
        "commercial_strategic",
    ]
    likelihood: Literal["HIGH", "MEDIUM", "LOW"]
    why_likely: str
    citation: Citation
    strategy_note: str
    relevant_career_entry_ids: list[str]


class LikelyQuestionsOutput(BaseModel):
    questions: list[LikelyQuestion]


class SalaryRecommendation(BaseModel):
    opening_number: int
    opening_phrasing: str
    floor: int
    ceiling: int
    reasoning: list[ReasoningPoint]
    sponsor_constraint_active: bool
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    scripts: dict
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


class LatexCVOutput(BaseModel):
    """Output of the cv_latex_writer agent — .tex source plus metadata."""

    template: Literal["modern_one_column", "traditional_two_column"]
    tex_source: str
    packages_used: list[str] = Field(default_factory=list)
    writer_notes: str = ""


class LatexRepairOutput(BaseModel):
    """Output of the cv_latex_repairer agent — patched .tex source.

    Empty `tex_source` + reason-prefixed `change_summary` signals the
    repairer gave up. The renderer detects this and exits cleanly.
    """

    tex_source: str
    change_summary: str


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
# Content Shield (AGENTS.md §18)
# ---------------------------------------------------------------------------


class ContentShieldVerdict(BaseModel):
    classification: Literal["SAFE", "SUSPICIOUS", "MALICIOUS"]
    reasoning: str
    residual_patterns_detected: list[str] = Field(default_factory=list)
    recommended_action: Literal["PASS_THROUGH", "PASS_WITH_WARNING", "REJECT"]


# ---------------------------------------------------------------------------
# Managed Agents — company investigator output
#
# See `src/trajectory/managed/company_investigator.py`. The MA agent
# returns an `InvestigatorOutput` JSON object. The investigator module
# converts it to `CompanyResearch` + `ExtractedJobDescription` and the
# conversion is the citation-enforcement boundary: every finding's
# `verbatim_snippet` must appear in one of the pages actually fetched
# during the session.
# ---------------------------------------------------------------------------


class InvestigatorFinding(BaseModel):
    claim: str
    source_url: str
    verbatim_snippet: str  # MUST appear verbatim in a fetched page's text


class QueuedJob(BaseModel):
    """A saved-for-later job URL awaiting batch processing.

    The queue is a distinct table from `sessions` — a queue entry
    exists before any Phase 1 work runs, and transitions to
    `status="done"` with a `session_id` pointer once processed. On
    failure, the entry sticks around for retry.
    """

    id: str
    user_id: str
    job_url: str
    status: Literal["pending", "processing", "done", "failed"]
    session_id: Optional[str] = None
    error: Optional[str] = None
    added_at: datetime
    processed_at: Optional[datetime] = None


class InvestigatorOutput(BaseModel):
    company_name: str
    company_domain: Optional[str] = None
    culture_claims: list[InvestigatorFinding] = Field(default_factory=list)
    tech_stack_signals: list[InvestigatorFinding] = Field(default_factory=list)
    team_size_signals: list[InvestigatorFinding] = Field(default_factory=list)
    recent_activity_signals: list[InvestigatorFinding] = Field(default_factory=list)
    posted_salary_bands: list[InvestigatorFinding] = Field(default_factory=list)
    careers_page_url: Optional[str] = None
    not_on_careers_page: bool = False
    extracted_jd: ExtractedJobDescription
    investigation_notes: str


# ---------------------------------------------------------------------------
# Prompt Auditor (AGENTS.md §17, build-time)
# ---------------------------------------------------------------------------


class ChecklistResult(BaseModel):
    item: str
    result: Literal["PASS", "FAIL", "WEAK", "N/A"]
    note: str


class ConcreteWeakness(BaseModel):
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    description: str
    proposed_patch: str


class InjectionStressTest(BaseModel):
    attempted_payload: str
    predicted_behaviour: Literal["REJECTS", "COMPLIES", "UNCLEAR"]
    reasoning: str


class PromptAuditReport(BaseModel):
    audited_agent_name: str
    overall_assessment: Literal["STRONG", "ADEQUATE", "WEAK", "UNSAFE"]
    checklist: list[ChecklistResult]
    concrete_weaknesses: list[ConcreteWeakness] = Field(default_factory=list)
    injection_stress_test: InjectionStressTest


# ---------------------------------------------------------------------------
# Resolve forward references
# ---------------------------------------------------------------------------

Session.model_rebuild()
Verdict.model_rebuild()
