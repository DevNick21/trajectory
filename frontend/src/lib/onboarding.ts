import { useEffect, useState } from "react";
import type { OnboardingAnswers } from "./types";
import type { OnboardingFinalisePayload } from "./api";

// Wizard state lives in browser localStorage (ADR-003 — no server-side
// session). This hook is the single source of truth: read-on-mount,
// write-on-change. Resume-on-refresh is free.

const STORAGE_KEY = "trajectory.onboarding";

export const initialAnswers: OnboardingAnswers = {
  name: "",
  base_location: "",
  user_type: "",
  visa_route: "",
  visa_expiry: "",
  nationality: "",
  salary_floor: null,
  salary_target: null,
  current_employment: "",
  search_duration_months: null,
  life_constraints: [],
  motivations_text: "",
  deal_breakers_text: "",
  good_role_signals_text: "",
  career_narrative: "",
  writing_samples: [],
};

function loadAnswers(): OnboardingAnswers {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return initialAnswers;
    const parsed = JSON.parse(raw);
    return { ...initialAnswers, ...parsed };
  } catch {
    return initialAnswers;
  }
}

function saveAnswers(a: OnboardingAnswers): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(a));
  } catch {
    // localStorage might be disabled (private browsing etc); persist
    // failure is silent — user still gets an in-memory wizard.
  }
}

export function clearOnboardingDraft(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // no-op
  }
}

export function useOnboardingDraft() {
  const [answers, setAnswers] = useState<OnboardingAnswers>(() => loadAnswers());

  useEffect(() => {
    saveAnswers(answers);
  }, [answers]);

  const update = (patch: Partial<OnboardingAnswers>) =>
    setAnswers((prev) => ({ ...prev, ...patch }));

  return { answers, update, reset: () => setAnswers(initialAnswers) };
}

// ---------------------------------------------------------------------------
// Validation: is this wizard state finalise-ready?
// ---------------------------------------------------------------------------

export function validateForFinalise(
  answers: OnboardingAnswers,
): { ok: true; payload: OnboardingFinalisePayload } | { ok: false; missing: string[] } {
  const missing: string[] = [];
  if (!answers.name.trim()) missing.push("name");
  if (!answers.base_location.trim()) missing.push("base_location");
  if (!answers.user_type) missing.push("user_type");
  if (answers.salary_floor === null) missing.push("salary_floor");
  if (!answers.current_employment) missing.push("current_employment");
  if (answers.user_type === "visa_holder" && !answers.visa_route) {
    missing.push("visa_route");
  }

  if (missing.length > 0) {
    return { ok: false, missing };
  }

  const payload: OnboardingFinalisePayload = {
    name: answers.name.trim(),
    user_type: answers.user_type as "visa_holder" | "uk_resident",
    base_location: answers.base_location.trim(),
    salary_floor: answers.salary_floor as number,
    salary_target: answers.salary_target,
    current_employment: answers.current_employment as
      | "EMPLOYED"
      | "UNEMPLOYED"
      | "NOTICE_PERIOD",
    search_duration_months: answers.search_duration_months,
    motivations_text: answers.motivations_text,
    deal_breakers_text: answers.deal_breakers_text,
    good_role_signals_text: answers.good_role_signals_text,
    life_constraints: answers.life_constraints,
    writing_samples: answers.writing_samples.filter((s) => s.trim().length > 0),
    career_narrative: answers.career_narrative,
  };

  if (answers.user_type === "visa_holder" && answers.visa_route) {
    payload.visa_route = answers.visa_route;
    payload.visa_expiry = answers.visa_expiry || undefined;
    payload.nationality = answers.nationality.trim() || undefined;
  }

  return { ok: true, payload };
}
