// TypeScript mirrors of the FastAPI response shapes. The generated OpenAPI
// contract in apps/web/src/generated is canonical for new routes; keep these
// hand-written shapes aligned with active callers.

// ---------------------------------------------------------------------------
// Profile
// ---------------------------------------------------------------------------

export type UserType = "visa_holder" | "uk_resident";

export interface UserProfile {
  user_id: string;
  name: string;
  user_type: UserType;
  base_location: string;
  salary_floor: number;
  salary_target?: number | null;
  motivations: string[];
  deal_breakers: string[];
  good_role_signals: string[];
  current_employment: "EMPLOYED" | "UNEMPLOYED" | "NOTICE_PERIOD";
  search_started_date: string;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Research Bundle & Verdict (Forensic Lab Data)
// ---------------------------------------------------------------------------

export interface JDData {
  role_title?: string;
  location?: string;
  remote_policy?: string;
  seniority_signal?: string;
  soc_code_guess?: string;
  salary_band?: { min_gbp?: number; max_gbp?: number; period?: string } | null;
  required_skills?: string[];
  posted_date?: string | null;
  specificity_signals?: string[];
  vagueness_signals?: string[];
}

export interface CompanyResearchData {
  company_name?: string;
  company_domain?: string | null;
  careers_page_url?: string | null;
  not_on_careers_page?: boolean;
  culture_claims?: Array<{ claim?: string; url?: string }>;
  tech_stack_signals?: string[];
  team_size_signals?: string[];
  recent_activity_signals?: string[];
  posted_salary_bands?: string[];
  policies?: Record<string, unknown>;
}

export interface CompaniesHouseData {
  status?: string;
  company_name_official?: string;
  accounts_overdue?: boolean;
  confirmation_statement_overdue?: boolean;
  filing_history_summary?: string;
}

export interface SponsorStatusData {
  status: "LISTED" | "NOT_LISTED" | "B_RATED" | "SUSPENDED" | "UNKNOWN" | "AMBIGUOUS";
  matched_name?: string | null;
  rating?: string | null;
  city?: string | null;
  county?: string | null;
  route?: string | null;
}

export interface SOCCheckData {
  soc_code: string;
  soc_title: string;
  going_rate_gbp: number | null;
  offered_salary_gbp: number | null;
  below_threshold: boolean;
  shortfall_gbp: number;
}

export interface GhostJobSignal {
  type: string;
  evidence: string;
  severity?: "HARD" | "SOFT";
  citation?: Citation;
}

export interface GhostJobData {
  probability: "LIKELY_GHOST" | "POSSIBLE_GHOST" | "LIKELY_REAL";
  confidence: "HIGH" | "MEDIUM" | "LOW";
  specificity_score: number;
  age_days: number | null;
  signals: GhostJobSignal[];
}

export interface RedFlag {
  type: string;
  summary: string;
  severity: "HARD" | "SOFT";
  citation?: Citation;
}

export interface ResearchBundle {
  extracted_jd?: JDData;
  company_research?: CompanyResearchData;
  companies_house?: CompaniesHouseData | null;
  sponsor_status?: SponsorStatusData | null;
  soc_check?: SOCCheckData | null;
  ghost_job?: GhostJobData;
  red_flags?: { flags: RedFlag[] };
  salary_signals?: {
    sources_consulted: string[];
  };
}

export interface VerdictReasoningPoint {
  claim: string;
  supporting_evidence?: string;
  citation?: Citation;
}

export interface HardBlocker {
  type: string;
  detail: string;
  citation: Citation;
}

export interface StretchConcern {
  type: string;
  detail: string;
  citation: Citation;
}

// Verdict label taxonomy — matches backend VerdictLabel Literal
export type VerdictLabel =
  | "STRONG_GO"
  | "GO"
  | "TRY_ANYWAY"
  | "ASK_FIRST"
  | "PASS"
  | "BLOCKED";

export interface VerdictPayload {
  decision: VerdictLabel;
  headline: string;
  confidence_pct: number;
  entropy_norm: number;
  reasoning: VerdictReasoningPoint[];
  hard_blockers: HardBlocker[];
  stretch_concerns: StretchConcern[];
  audit_metadata?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export interface SessionSummary {
  id: string;
  job_url: string | null;
  intent: string;
  created_at: string;
  verdict: VerdictLabel | null;
  role_title: string | null;
  company_name: string | null;
}

export interface SessionListResponse {
  sessions: SessionSummary[];
}

export interface GeneratedFile {
  filename: string;
  size_bytes: number;
  kind: "docx" | "pdf" | "latex_pdf" | "other";
  download_url: string;
}

export interface CostSummary {
  total_usd: number;
  by_agent: Record<string, number>;
}

// research_bundle + verdict pass through as raw JSON; the dashboard
// reads what it cares about and ignores the rest. Tightening these
// types is a follow-up if we add codegen.
export interface SessionDetailResponse {
  id: string;
  user_id: string;
  job_url: string | null;
  intent: string;
  created_at: string;
  research_bundle: ResearchBundle | null;
  verdict: VerdictPayload | null;
  generated_files: GeneratedFile[];
  cost_summary: CostSummary;
  progress_events: Record<string, unknown>[];
}

// ---------------------------------------------------------------------------
// Pack endpoints
// ---------------------------------------------------------------------------

export type PackGeneratorName = "cv" | "cover_letter" | "questions" | "salary";

export interface PackResult {
  generator: PackGeneratorName;
  output: Record<string, unknown>;
  generated_files: GeneratedFile[];
}

// ---------------------------------------------------------------------------
// Offer analysis (PROCESS Entry 43, Workstream F)
// ---------------------------------------------------------------------------

export interface Citation {
  kind: "url_snippet" | "gov_data" | "career_entry";
  url?: string | null;
  verbatim_snippet?: string | null;
  data_field?: string | null;
  data_value?: string | null;
  entry_id?: string | null;
}

export interface OfferComponent {
  label: string;
  value_text: string;
  citation: Citation;
}

// ---------------------------------------------------------------------------
// Career entries (GET /api/career-entries)
// ---------------------------------------------------------------------------

export type CareerEntryKind =
  | "cv_bullet"
  | "qa_answer"
  | "star_polish"
  | "project_note"
  | "preference"
  | "motivation"
  | "deal_breaker"
  | "good_role_signal"
  | "conversation";

export interface CareerEntry {
  entry_id: string;
  user_id: string;
  kind: CareerEntryKind;
  raw_text: string;
  structured?: Record<string, unknown> | null;
  source_session_id?: string | null;
  created_at: string;
}

export interface CareerEntriesResponse {
  entries: CareerEntry[];
}

// ---------------------------------------------------------------------------
// Application-assist memory graph
// ---------------------------------------------------------------------------

export type QuestionType =
  | "technical"
  | "competency"
  | "motivation"
  | "screening"
  | "values"
  | "cover_letter"
  | "visa"
  | "salary"
  | "other";

export type MemoryReviewStatus = "pending" | "approved" | "hidden" | "deleted";
export type MemoryVisibility = "normal" | "private";

export interface ExperienceAtom {
  atom_id: string;
  user_id: string;
  atom_type:
    | "skill"
    | "metric"
    | "responsibility"
    | "project"
    | "result"
    | "conflict"
    | "preference"
    | "credential"
    | "constraint"
    | "other";
  text: string;
  source_type:
    | "cv"
    | "transcript"
    | "answer"
    | "uploaded_file"
    | "manual_edit"
    | "onboarding"
    | "generated_answer";
  source_id?: string | null;
  source_excerpt?: string | null;
  confidence: number;
  sensitive: boolean;
  visibility: MemoryVisibility;
  review_status: MemoryReviewStatus;
  created_at: string;
  updated_at: string;
}

export interface StoryFrame {
  story_id: string;
  user_id: string;
  title: string;
  summary: string;
  angle_tags: string[];
  question_types: QuestionType[];
  atom_ids: string[];
  outcome_score: number;
  usage_count: number;
  sensitive: boolean;
  visibility: MemoryVisibility;
  review_status: MemoryReviewStatus;
  created_at: string;
  updated_at: string;
}

export interface MemoryInboxResponse {
  experience_atoms: ExperienceAtom[];
  story_frames: StoryFrame[];
}

export interface QuestionPattern {
  question_type: QuestionType;
  what_testing: string;
  ideal_evidence: string[];
  structure_hint: string;
  common_failures: string[];
  confidence: "HIGH" | "MEDIUM" | "LOW";
}

export interface MemorySuggestion {
  memory_id: string;
  memory_kind: "career_entry" | "experience_atom" | "story_frame";
  title: string;
  text: string;
  score: number;
  rationale: string;
  warnings: string[];
  outcome_signal?: "positive" | "weak" | null;
}

export interface ApplicationAssistSession {
  assist_session_id: string;
  user_id: string;
  session_id?: string | null;
  job_id?: string | null;
  job_url?: string | null;
  company_name?: string | null;
  role_title?: string | null;
  jd_text?: string | null;
  private_mode: boolean;
  created_at: string;
  updated_at: string;
}

export interface AssistStartResponse {
  assist_session: ApplicationAssistSession;
}

export interface AdviceSnippet {
  advice_id: string;
  title: string;
  body: string;
  source_url: string;
  source_type: "official" | "university" | "employer" | "curated" | "other";
  topic_tags: string[];
  licence_status: string;
  citation_text: string;
  created_at: string;
}

export interface AnswerRubricScore {
  dimension:
    | "directness"
    | "evidence"
    | "specificity"
    | "result"
    | "role_fit"
    | "word_limit"
    | "voice";
  score: number;
  note: string;
}

export interface AnswerCritique {
  question_type: QuestionType;
  what_testing: string;
  scores: AnswerRubricScore[];
  targeted_nudge?: string | null;
  missing_evidence: string[];
  word_count: number;
  word_limit_status: "under" | "near" | "over" | "unknown";
  suggested_angles: MemorySuggestion[];
  advice_snippets: AdviceSnippet[];
}

export interface SuggestMemoryResponse {
  pattern: QuestionPattern;
  suggestions: MemorySuggestion[];
  advice_snippets: AdviceSnippet[];
}

export interface CritiqueDraftResponse {
  attempt_id: string;
  critique: AnswerCritique;
  save_indicator: "Saved privately" | "Pending review" | "Not saved";
}

export interface ApplicationAnswerOutput {
  final_answer: string;
  word_count: number;
  question_type: QuestionType;
  structure_used: string;
  citations: Citation[];
  memory_ids_used: string[];
  missing_evidence_flags: string[];
  save_indicator: "Saved privately" | "Pending review" | "Not saved";
}

export interface PolishAssistResponse {
  attempt_id: string;
  output: ApplicationAnswerOutput;
}

export interface ApproveAssistResponse {
  attempt_id: string;
  memory_items_created: number;
  inbox_status: "pending_review";
  save_indicator: "Saved privately" | "Pending review" | "Not saved";
}

export interface MemoryExportResponse {
  answer_attempts: Array<{
    attempt_id: string;
    user_id: string;
    question_text: string;
    question_type: QuestionType;
    raw_draft: string;
    transcript?: string | null;
    final_answer?: string | null;
    visibility: MemoryVisibility;
    save_status: "auto_saved" | "approved" | "not_saved";
    raw_retention_until: string;
    created_at: string;
    updated_at: string;
  }>;
  experience_atoms: ExperienceAtom[];
  story_frames: StoryFrame[];
}

// ---------------------------------------------------------------------------
// CV pack output (PackResult.output when generator === "cv")
// Mirrors askpicky.schemas.CVOutput / CVRole / CVBullet.
// ---------------------------------------------------------------------------

export interface CVBullet {
  text: string;
  citations: Citation[];
}

export interface CVRole {
  title: string;
  company: string;
  dates: string;
  bullets: CVBullet[];
}

export interface CVOutput {
  name: string;
  contact: Record<string, unknown>;
  professional_summary: string;
  experience: CVRole[];
  education: Array<Record<string, unknown>>;
  skills: string[];
  projects?: Array<Record<string, unknown>> | null;
}

// ---------------------------------------------------------------------------
// Cover letter pack output
// ---------------------------------------------------------------------------

export interface CoverLetterOutput {
  addressed_to: string;
  paragraphs: string[];
  citations: Citation[];
  word_count: number;
}

// ---------------------------------------------------------------------------
// Salary recommendation pack output
// ---------------------------------------------------------------------------

export interface ReasoningPoint {
  claim: string;
  supporting_evidence: string;
  citation: Citation;
}

export interface SalaryRecommendation {
  opening_number: number;
  opening_phrasing: string;
  floor: number;
  ceiling: number;
  reasoning: ReasoningPoint[];
  sponsor_constraint_active: boolean;
  confidence: "HIGH" | "MEDIUM" | "LOW";
  scripts: Record<string, string>;
  data_gaps: string[];
  urgency_note?: string | null;
}

// ---------------------------------------------------------------------------
// Likely interview questions pack output
// ---------------------------------------------------------------------------

export type QuestionBucket =
  | "technical"
  | "experience"
  | "behavioural"
  | "motivation_fit"
  | "commercial_strategic";

export interface LikelyQuestion {
  question: string;
  bucket: QuestionBucket;
  likelihood: "HIGH" | "MEDIUM" | "LOW";
  why_likely: string;
  citation: Citation;
  strategy_note: string;
  relevant_career_entry_ids: string[];
}

export interface LikelyQuestionsOutput {
  questions: LikelyQuestion[];
}

export interface OfferAnalysis {
  company_name: string;
  role_title: string | null;
  base_salary_gbp: OfferComponent | null;
  bonus: OfferComponent | null;
  equity: OfferComponent | null;
  benefits: OfferComponent[];
  notice_period: OfferComponent | null;
  non_compete: OfferComponent | null;
  ip_assignment: OfferComponent | null;
  unusual_clauses: OfferComponent[];
  market_comparison_note: string | null;
  flags: string[];
}

// Wire shape from POST /api/sessions/{id}/offer.
export interface OfferAnalysisResponse {
  generator: "offer";
  output: OfferAnalysis;
}

// ---------------------------------------------------------------------------
// Onboarding wizard
// ---------------------------------------------------------------------------

export type VisaRoute =
  | "graduate"
  | "skilled_worker"
  | "dependant"
  | "student"
  | "global_talent"
  | "other";

export type EmploymentStatus = "EMPLOYED" | "UNEMPLOYED" | "NOTICE_PERIOD";

export interface OnboardingAnswers {
  // Basics
  name: string;
  base_location: string;
  // Visa
  user_type: UserType | "";
  visa_route: VisaRoute | "";
  visa_expiry: string; // ISO date
  nationality: string;
  // Money
  salary_floor: number | null;
  salary_target: number | null;
  // Work context
  current_employment: EmploymentStatus | "";
  search_duration_months: number | null;
  life_constraints: string[];
  // Voice stages
  motivations_text: string;
  deal_breakers_text: string;
  good_role_signals_text: string;
  // Career narrative (optional)
  career_narrative: string;
}

export interface OnboardingFinaliseResponse {
  user_id: string;
  career_entries_written: number;
}

// ---------------------------------------------------------------------------
// JD-first local analysis
// ---------------------------------------------------------------------------

export type ApplicationPriority =
  | "worth_applying_with_tailoring"
  | "maybe_apply_after_checking_filters"
  | "low_priority";

export interface LocalHardFilter {
  label: string;
  evidence: string;
  severity: "hard" | "check";
}

export interface LocalJobAnalysis {
  role_title: string;
  required_skills: string[];
  hard_filters: LocalHardFilter[];
  missing_evidence_prompts: string[];
  application_priority: ApplicationPriority;
  answer_strategy: string[];
}

export interface JobAnalysisResponse {
  analysis: LocalJobAnalysis;
}

// ---------------------------------------------------------------------------
// SSE event vocabularies
// ---------------------------------------------------------------------------

// POST /api/sessions/forward_job
export type ForwardJobEvent =
  | { type: "session_started"; session_id: string; job_url: string }
  | { type: "agent_started"; agent: string }
  | { type: "agent_complete"; agent: string }
  | { type: "agent_failed"; agent: string; error?: string }
  | { type: "verdict"; data: VerdictPayload }
  | { type: "error"; data: { message: string } }
  | { type: "done" };

// POST /api/sessions/{id}/full_prep
export type FullPrepEvent =
  | { type: "started"; generator: PackGeneratorName }
  | {
      type: "completed";
      generator: PackGeneratorName;
      data: Record<string, unknown>;
      generated_files: GeneratedFile[];
    }
  | { type: "failed"; generator: PackGeneratorName; error: string }
  | { type: "error"; data: { message: string } }
  | { type: "done" };

// ---------------------------------------------------------------------------
// Queue (batch processing — #5)
// ---------------------------------------------------------------------------

export type QueueItemStatus = "pending" | "processing" | "done" | "failed";

export interface QueueItem {
  id: string;
  job_url: string;
  status: QueueItemStatus;
  session_id: string | null;
  error: string | null;
  added_at: string;
  processed_at: string | null;
}

export interface QueueListResponse {
  items: QueueItem[];
  pending_count: number;
  processing_count: number;
  done_count: number;
  failed_count: number;
}

// POST /api/queue/process
export type QueueBatchEvent =
  | { type: "started"; id: string; job_url: string }
  | {
      type: "completed";
      id: string;
      session_id: string;
      verdict_decision: VerdictLabel;
      verdict_headline: string;
      role_title: string | null;
      company_name: string | null;
    }
  | { type: "failed"; id: string; error: string }
  | { type: "error"; data: { message: string } }
  | { type: "done"; processed_count?: number; note?: string };

// ---------------------------------------------------------------------------
// Manual application tracker
// ---------------------------------------------------------------------------

export type ApplicationStatus =
  | "forwarded"
  | "applied"
  | "no_response"
  | "rejected_screen"
  | "rejected_interview"
  | "rejected_offer"
  | "offer_received"
  | "offer_accepted"
  | "offer_declined";

export interface ApplicationRecord {
  id: number;
  user_id: string;
  session_id: string;
  company_name: string;
  role_title: string;
  job_url: string | null;
  verdict_decision: string | null;
  status: ApplicationStatus;
  applied_at: string | null;
  last_status_at: string;
  notes: string | null;
  created_at: string;
}

export interface ApplicationListResponse {
  applications: ApplicationRecord[];
}

export type OutcomeKind = Exclude<ApplicationStatus, "forwarded">;

// ---------------------------------------------------------------------------
// Error envelope (HTTPException(detail={...}) shape)
// ---------------------------------------------------------------------------

export interface ApiErrorBody {
  detail:
    | string
    | {
        code?: "profile_not_found" | "session_not_found" | "precondition_failed" | "file_not_found" | "invalid_filename";
        message?: string;
      };
}

// ---------------------------------------------------------------------------
