// Typed fetch wrappers — one per endpoint. Wave 6 stubs the contract
// the dashboard (Wave 7) and detail page (Wave 8) consume. SSE
// endpoints live in lib/sse.ts.

import type {
  PackGeneratorName,
  PackResult,
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
// File download URL (no fetch — the browser navigates to it directly)
// ---------------------------------------------------------------------------

export const fileUrl = (sessionId: string, filename: string) =>
  `/api/files/${encodeURIComponent(sessionId)}/${encodeURIComponent(filename)}`;
