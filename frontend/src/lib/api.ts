// Typed fetch wrappers — one per endpoint. Wave 6 stubs the contract
// the dashboard (Wave 7) and detail page (Wave 8) consume. SSE
// endpoints live in lib/sse.ts.

import type {
  CareerEntriesResponse,
  CareerEntryKind,
  OfferAnalysisResponse,
  OnboardingAnswers,
  OnboardingFinaliseResponse,
  PackGeneratorName,
  PackResult,
  QueueItem,
  QueueListResponse,
  SessionDetailResponse,
  SessionListResponse,
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
  return (await resp.json()) as T;
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  storage_initialised: boolean;
  demo_user_id_configured: boolean;
}

export const getHealth = () => request<HealthResponse>("/health");

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
  writing_samples: string[];
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
//   POST /api/chat — natural-language entrypoint mirroring the Telegram bot.
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
// File download URL (no fetch — the browser navigates to it directly)
// ---------------------------------------------------------------------------

export const fileUrl = (sessionId: string, filename: string) =>
  `/api/files/${encodeURIComponent(sessionId)}/${encodeURIComponent(filename)}`;
