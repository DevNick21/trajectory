// Typed fetch wrappers — one per endpoint. Wave 6 stubs the contract
// the dashboard (Wave 7) and detail page (Wave 8) consume. SSE
// endpoints live in lib/sse.ts.

import type {
  ApplicationListResponse,
  ApplicationResponse,
  ApplicationStatus,
  ApproveAssistResponse,
  AssistStartResponse,
  CritiqueDraftResponse,
  CareerEntriesResponse,
  CareerEntryKind,
  JobAnalysisResponse,
  MemoryExportResponse,
  MemoryInboxResponse,
  MemoryReviewStatus,
  MemoryVisibility,
  OfferAnalysisResponse,
  OnboardingAnswers,
  OnboardingFinaliseResponse,
  OutcomeKind,
  PackGeneratorName,
  PackResult,
  PolishAssistResponse,
  QueueItem,
  QueueListResponse,
  SessionDetailResponse,
  SessionListResponse,
  SuggestMemoryResponse,
  UserProfile,
} from "./types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code?: string,
    message?: string,
  ) {
    super(message ?? `HTTP ${status}`);
    this.name = "ApiError";
  }
}

async function request<T>(
  url: string,
  init?: RequestInit,
): Promise<T> {
  const resp = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!resp.ok) {
    let code: string | undefined;
    let message: string | undefined;
    try {
      const body = await resp.json();
      const detail = body?.detail;
      if (typeof detail === "string") {
        message = detail;
      } else if (detail && typeof detail === "object") {
        code = detail.code;
        message = detail.message;
      }
    } catch {
      // Non-JSON body — fall through with status only.
    }
    throw new ApiError(resp.status, code, message);
  }
  if (resp.status === 204) {
    return undefined as T;
  }
  return (await resp.json()) as T;
}

// ---------------------------------------------------------------------------
// Profile
// ---------------------------------------------------------------------------

export const getProfile = () => request<UserProfile>("/api/profile");

// ---------------------------------------------------------------------------
// Sessions (read-only — POST /api/sessions/forward_job lives in sse.ts)
// ---------------------------------------------------------------------------

export const listSessions = (limit = 20) =>
  request<SessionListResponse>(`/api/sessions?limit=${limit}`);

export const getSession = (id: string) =>
  request<SessionDetailResponse>(`/api/sessions/${encodeURIComponent(id)}`);

export const analyseJobDescription = (jdText: string) =>
  request<JobAnalysisResponse>("/api/job-analysis", {
    method: "POST",
    body: JSON.stringify({ jd_text: jdText }),
  });

// ---------------------------------------------------------------------------
// Pack endpoints (individual — full_prep lives in sse.ts)
// ---------------------------------------------------------------------------

export const generatePack = (
  sessionId: string,
  generator: PackGeneratorName,
) =>
  request<PackResult>(
    `/api/sessions/${encodeURIComponent(sessionId)}/${generator}`,
    { method: "POST" },
  );

// ---------------------------------------------------------------------------
// Career entries (powers Deep Work left pane)
// ---------------------------------------------------------------------------

export const listCareerEntries = (kinds?: CareerEntryKind[]) => {
  const qs = kinds && kinds.length > 0 ? `?kinds=${kinds.join(",")}` : "";
  return request<CareerEntriesResponse>(`/api/career-entries${qs}`);
};

// ---------------------------------------------------------------------------
// Memory Inbox (application-assist private evidence graph)
// ---------------------------------------------------------------------------

export const listMemoryInbox = (status: MemoryReviewStatus = "pending") =>
  request<MemoryInboxResponse>(
    `/api/memory/inbox?status_filter=${encodeURIComponent(status)}`,
  );

export const updateMemoryInboxItem = (
  itemKind: "experience_atom" | "story_frame",
  itemId: string,
  payload: {
    review_status: MemoryReviewStatus;
    visibility?: MemoryVisibility;
    text?: string;
    title?: string;
    summary?: string;
    angle_tags?: string[];
    question_types?: string[];
  },
) =>
  request<{ ok: boolean }>(
    `/api/memory/inbox/${itemKind}/${encodeURIComponent(itemId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );

export const hardDeleteMemoryInboxItem = (
  itemKind: "experience_atom" | "story_frame",
  itemId: string,
) =>
  request<{ ok: boolean }>(
    `/api/memory/inbox/${itemKind}/${encodeURIComponent(itemId)}`,
    { method: "DELETE" },
  );

export const mergeMemoryInboxItems = (payload: {
  item_kind: "experience_atom" | "story_frame";
  target_item_id: string;
  source_item_ids: string[];
  merged_text?: string;
  title?: string;
  visibility?: MemoryVisibility;
}) =>
  request<{ ok: boolean; merged_count: number }>("/api/memory/inbox/merge", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const exportMemory = (includeRaw = true) =>
  request<MemoryExportResponse>(
    `/api/memory/export?include_raw=${includeRaw ? "true" : "false"}`,
  );

export const purgeExpiredMemoryRaw = () =>
  request<{ purged_attempts: number }>("/api/memory/privacy/purge-expired", {
    method: "POST",
  });

// ---------------------------------------------------------------------------
// Application assist (question -> memory -> nudge -> polish)
// ---------------------------------------------------------------------------

export const startAssistSession = (payload: {
  session_id?: string | null;
  job_id?: string | null;
  job_url?: string | null;
  company_name?: string | null;
  role_title?: string | null;
  jd_text?: string | null;
  private_mode?: boolean;
}) =>
  request<AssistStartResponse>("/api/assist/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export interface AssistDraftPayload {
  question_text: string;
  jd_text?: string;
  raw_draft?: string;
  transcript?: string | null;
  word_limit?: number | null;
  question_type?: string | null;
  assist_session_id?: string | null;
  include_private?: boolean;
  selected_memory_ids?: string[];
}

export const suggestAssistMemory = (payload: {
  assist_session_id?: string | null;
  question_text: string;
  jd_text?: string;
  question_type?: string | null;
  k?: number;
  include_private?: boolean;
}) =>
  request<SuggestMemoryResponse>("/api/assist/suggest-memory", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const critiqueAssistDraft = (payload: AssistDraftPayload) =>
  request<CritiqueDraftResponse>("/api/assist/critique-draft", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const polishAssistAnswer = (
  payload: AssistDraftPayload & { attempt_id?: string | null },
) =>
  request<PolishAssistResponse>("/api/assist/polish", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const approveAssistAnswer = (payload: {
  attempt_id: string;
  final_answer?: string;
  selected_memory_ids?: string[];
}) =>
  request<ApproveAssistResponse>("/api/assist/approve", {
    method: "POST",
    body: JSON.stringify(payload),
  });

// ---------------------------------------------------------------------------
// Onboarding (Wave 9)
// ---------------------------------------------------------------------------

// Finalise payload matches OnboardingFinaliseRequest in api/schemas.py.
// Numeric fields are nullable client-side so the wizard can defer
// until the user fills them in; we coerce + validate before POSTing.
export interface OnboardingFinalisePayload {
  name: string;
  user_type: "visa_holder" | "uk_resident";
  visa_route?: OnboardingAnswers["visa_route"];
  visa_expiry?: string;
  nationality?: string;
  base_location: string;
  salary_floor: number;
  salary_target?: number | null;
  current_employment: OnboardingAnswers["current_employment"];
  search_duration_months?: number | null;
  motivations_text: string;
  deal_breakers_text: string;
  good_role_signals_text: string;
  life_constraints: string[];
  career_narrative: string;
}

export const finaliseOnboarding = (payload: OnboardingFinalisePayload) =>
  request<OnboardingFinaliseResponse>("/api/onboarding/finalise", {
    method: "POST",
    body: JSON.stringify(payload),
  });

// ---------------------------------------------------------------------------
// Queue (#5)
// ---------------------------------------------------------------------------

export const addToQueue = (jobUrls: string[]) =>
  request<QueueItem[]>("/api/queue", {
    method: "POST",
    body: JSON.stringify({ job_urls: jobUrls }),
  });

export const listQueue = () => request<QueueListResponse>("/api/queue");

export const removeFromQueue = async (id: string): Promise<void> => {
  const resp = await fetch(`/api/queue/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!resp.ok && resp.status !== 204) {
    throw new ApiError(resp.status, undefined, `DELETE failed: ${resp.status}`);
  }
};

// ---------------------------------------------------------------------------
// Chat (PROCESS Entry 45)
//   POST /api/chat — natural-language entrypoint.
//   Returns either a redirect target (for forward_job / draft_* etc.) or
//   an inline text/card response.
// ---------------------------------------------------------------------------

export interface ChatResponse {
  intent: string;
  confidence: "HIGH" | "MEDIUM" | "LOW";
  reply_kind: "text" | "redirect" | "card";
  text?: string | null;
  redirect_to?: string | null;
  payload?: Record<string, unknown> | null;
  reasoning_brief?: string | null;
}

export const sendChat = (message: string, sessionId?: string) =>
  request<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify({ message, session_id: sessionId }),
  });

// ---------------------------------------------------------------------------
// Offer analysis (PROCESS Entry 43, Workstream F)
//   POST /api/sessions/{id}/offer  — multipart form. Pass either a PDF
//   File OR a text string. `sessionId="none"` runs without a research
//   bundle for market comparison.
// ---------------------------------------------------------------------------

export interface AnalyseOfferInput {
  sessionId?: string;             // omit or "none" -> standalone analysis
  pdf?: File;                     // forwarded offer letter PDF
  text?: string;                  // pasted offer letter text
}

export const analyseOffer = async (
  input: AnalyseOfferInput,
): Promise<OfferAnalysisResponse> => {
  if (!input.pdf && !(input.text && input.text.trim())) {
    throw new ApiError(400, "missing_input", "Provide a PDF file or text.");
  }
  const sessionId = input.sessionId && input.sessionId.trim()
    ? input.sessionId
    : "none";

  const form = new FormData();
  if (input.pdf) form.append("pdf", input.pdf);
  if (input.text) form.append("text", input.text);

  const resp = await fetch(
    `/api/sessions/${encodeURIComponent(sessionId)}/offer`,
    { method: "POST", body: form },
  );
  if (!resp.ok) {
    let code: string | undefined;
    let message: string | undefined;
    try {
      const body = await resp.json();
      const detail = body?.detail;
      if (typeof detail === "string") message = detail;
      else if (detail && typeof detail === "object") {
        code = detail.code;
        message = detail.message;
      }
    } catch {
      /* non-JSON body */
    }
    throw new ApiError(resp.status, code, message);
  }
  return (await resp.json()) as OfferAnalysisResponse;
};

// ---------------------------------------------------------------------------
// Onboarding CV import (PROCESS Entry 49)
// ---------------------------------------------------------------------------

export interface CVImportRole {
  title: string;
  company: string;
  dates: string;
  bullets: string[];
}

export interface CVImportEducation {
  institution: string;
  qualification: string;
  dates: string;
}

export interface CVImportProject {
  name: string;
  description: string;
}

export interface CVImportResponse {
  name: string | null;
  base_location: string | null;
  contact_email: string | null;
  professional_summary: string | null;
  roles: CVImportRole[];
  education: CVImportEducation[];
  projects: CVImportProject[];
  skills: string[];
  // 2-3 paragraph chronological narrative bio produced by the same
  // Haiku call as the rest of the extraction.
  narrative?: string | null;
  raw_text: string;
  extraction_confidence: number;
}

export const importCV = async (file: File): Promise<CVImportResponse> => {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch("/api/onboarding/cv_import", {
    method: "POST",
    body: form,
  });
  if (!resp.ok) {
    let code: string | undefined;
    let message: string | undefined;
    try {
      const body = await resp.json();
      const detail = body?.detail;
      if (typeof detail === "string") message = detail;
      else if (detail && typeof detail === "object") {
        code = detail.code;
        message = detail.message;
      }
    } catch {
      /* non-JSON body */
    }
    throw new ApiError(resp.status, code, message);
  }
  return (await resp.json()) as CVImportResponse;
};

// ---------------------------------------------------------------------------
// Manual application tracker
// ---------------------------------------------------------------------------

export const listApplications = (
  opts: { status?: ApplicationStatus[]; limit?: number } = {},
): Promise<ApplicationListResponse> => {
  const params = new URLSearchParams();
  if (opts.status?.length) params.set("status", opts.status.join(","));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return request<ApplicationListResponse>(
    `/api/applications${qs ? `?${qs}` : ""}`,
  );
};

export const getApplication = (sessionId: string): Promise<ApplicationResponse> =>
  request(`/api/applications/${encodeURIComponent(sessionId)}`);

export const saveLocalApplication = (
  jdText: string,
  companyName?: string,
): Promise<ApplicationResponse> =>
  request("/api/applications/local", {
    method: "POST",
    body: JSON.stringify({ jd_text: jdText, company_name: companyName }),
  });

export const updateApplication = (
  sessionId: string,
  payload: { company_name?: string; role_title?: string; notes?: string },
): Promise<ApplicationResponse> =>
  request(`/api/applications/${encodeURIComponent(sessionId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const refreshApplicationEvidence = (
  sessionId: string,
): Promise<ApplicationResponse> =>
  request(`/api/applications/${encodeURIComponent(sessionId)}/refresh-evidence`, {
    method: "POST",
  });

export const updateApplicationStatus = (
  sessionId: string,
  status: ApplicationStatus,
  notes?: string,
): Promise<ApplicationResponse> =>
  request(`/api/applications/${encodeURIComponent(sessionId)}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status, notes }),
  });

export const deleteApplication = (sessionId: string): Promise<void> =>
  request(`/api/applications/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });

export const recordOutcome = (
  sessionId: string,
  outcome: OutcomeKind,
  notes?: string,
): Promise<{ ok: boolean; session_id: string; outcome: OutcomeKind }> =>
  request(`/api/sessions/${encodeURIComponent(sessionId)}/outcome`, {
    method: "POST",
    body: JSON.stringify({ outcome, notes }),
  });
