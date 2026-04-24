// TypeScript mirrors of the FastAPI response shapes (api/schemas.py +
// trajectory/schemas.py). Keep these synced manually for now —
// MIGRATION_PLAN.md §9 deferred a codegen step. If a backend Pydantic
// field renames, find and update here.

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
// Sessions
// ---------------------------------------------------------------------------

export interface SessionSummary {
  id: string;
  job_url: string | null;
  intent: string;
  created_at: string;
  verdict: "GO" | "NO_GO" | null;
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
  research_bundle: Record<string, unknown> | null;
  verdict: Record<string, unknown> | null;
  generated_files: GeneratedFile[];
  cost_summary: CostSummary;
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
  // Writing samples
  writing_samples: string[];
}

export interface OnboardingFinaliseResponse {
  user_id: string;
  writing_style_profile_id: string | null;
  career_entries_written: number;
}

// ---------------------------------------------------------------------------
// SSE event vocabularies
// ---------------------------------------------------------------------------

// POST /api/sessions/forward_job
export type ForwardJobEvent =
  | { type: "agent_complete"; agent: string }
  | { type: "verdict"; data: Record<string, unknown> }
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
      verdict_decision: "GO" | "NO_GO";
      verdict_headline: string;
      role_title: string | null;
      company_name: string | null;
    }
  | { type: "failed"; id: string; error: string }
  | { type: "error"; data: { message: string } }
  | { type: "done"; processed_count?: number; note?: string };

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
