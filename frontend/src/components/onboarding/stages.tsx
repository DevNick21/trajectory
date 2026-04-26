// Eight wizard stages, rendered one at a time by OnboardingWizard.
// Each stage is a small form that reads + writes via the shared
// OnboardingAnswers object from the useOnboardingDraft hook. No
// per-stage validation beyond "required fields filled" — that
// happens in validateForFinalise at submit time.

import { useState } from "react";

import { ApiError, importCV, type CVImportResponse } from "@/lib/api";
import type { OnboardingAnswers } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "./Textarea";

export interface StageProps {
  answers: OnboardingAnswers;
  update: (patch: Partial<OnboardingAnswers>) => void;
}

const LIFE_CONSTRAINT_OPTIONS = [
  "school pickup / drop-off windows",
  "caring responsibilities",
  "medical / health constraint",
  "cannot travel abroad",
  "partner / dual career constraint",
  "financial runway under 3 months",
];

// ---------------------------------------------------------------------------
// 0. CV upload — pre-fills the rest of the wizard from an existing CV.
//    Optional: skip with "Fill in manually" and the rest of the stages
//    work as before.
// ---------------------------------------------------------------------------

function applyCVImportToAnswers(
  imp: CVImportResponse,
  current: OnboardingAnswers,
): Partial<OnboardingAnswers> {
  // Build a career-narrative paragraph from the extracted roles so the
  // free-text "Career so far" stage already has substance the user can
  // edit. Skip if the user has already typed something there.
  const narrative = current.career_narrative.trim()
    ? current.career_narrative
    : imp.roles
        .slice(0, 3)
        .map(
          (r) =>
            `${r.title} at ${r.company} (${r.dates}). ${r.bullets.slice(0, 2).join(" ")}`.trim(),
        )
        .filter(Boolean)
        .join("\n\n");

  // Use the raw CV text as the first writing sample. style_extractor
  // benefits more from one full CV than from a 3-line "I am passionate
  // about…" paragraph.
  const samples =
    current.writing_samples.length > 0 && current.writing_samples.some((s) => s.trim())
      ? current.writing_samples
      : [imp.raw_text.slice(0, 4000)];

  return {
    name: current.name.trim() || imp.name?.trim() || current.name,
    base_location:
      current.base_location.trim() ||
      imp.base_location?.trim() ||
      current.base_location,
    career_narrative: narrative,
    writing_samples: samples,
  };
}

export function StageCVUpload({ answers, update }: StageProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<CVImportResponse | null>(null);

  const onFile = async (file: File) => {
    setError(null);
    setBusy(true);
    try {
      const out = await importCV(file);
      setLast(out);
      update(applyCVImportToAnswers(out, answers));
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message ?? "Upload failed."
          : err instanceof Error
            ? err.message
            : "Upload failed.";
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Start from your CV (recommended)</h2>
      <p className="text-sm text-muted-foreground">
        Upload your existing CV and we'll pre-fill name, location, career
        history, and writing samples — you review and edit on the next
        screens. No CV? Skip this and fill it in manually.
      </p>

      <label
        className={
          "flex cursor-pointer flex-col items-center justify-center " +
          "rounded-md border-2 border-dashed border-input bg-white " +
          "px-6 py-10 text-center text-card-foreground transition " +
          "hover:border-primary"
        }
      >
        <input
          type="file"
          accept=".pdf,.docx,.txt,.md"
          className="sr-only"
          disabled={busy}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void onFile(f);
            // reset so re-selecting the same file refires
            e.target.value = "";
          }}
        />
        {busy ? (
          <span className="text-sm">Reading your CV…</span>
        ) : (
          <>
            <span className="text-sm font-medium">
              Click to upload — PDF, DOCX, or text
            </span>
            <span className="mt-1 text-xs text-muted-foreground">
              5 MB max · stays on your device until you click Finish
            </span>
          </>
        )}
      </label>

      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

      {last && (
        <div className="rounded-md border bg-secondary/40 p-3 text-sm">
          <p className="font-medium">
            Extracted with confidence {last.extraction_confidence}/10
          </p>
          <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
            {last.name && <li>Name: {last.name}</li>}
            {last.base_location && <li>Location: {last.base_location}</li>}
            {last.contact_email && <li>Email: {last.contact_email}</li>}
            <li>{last.roles.length} role(s)</li>
            <li>{last.education.length} education entries</li>
            <li>{last.skills.length} skills</li>
          </ul>
          <p className="mt-2 text-xs">
            Move on to the next step to review and edit.
          </p>
        </div>
      )}

      <div className="flex items-center justify-between border-t pt-3 text-xs">
        <span className="text-muted-foreground">
          Skipping is fine — you can paste a CV in any text field later.
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setLast(null)}
          disabled={!last}
        >
          Reset
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 1. Basics — name + location
// ---------------------------------------------------------------------------

export function StageBasics({ answers, update }: StageProps) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">About you</h2>
      <p className="text-sm text-muted-foreground">
        The basics that appear in generated CVs and cover letters.
      </p>
      <div className="grid gap-3">
        <label className="block">
          <span className="text-sm font-medium">Name</span>
          <Input
            value={answers.name}
            onChange={(e) => update({ name: e.target.value })}
            placeholder="Jane Example"
            className="mt-1"
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium">Base location (UK city)</span>
          <Input
            value={answers.base_location}
            onChange={(e) => update({ base_location: e.target.value })}
            placeholder="London"
            className="mt-1"
          />
        </label>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 2. Visa — radio + conditional fields
// ---------------------------------------------------------------------------

const VISA_ROUTES: Array<{ value: string; label: string }> = [
  { value: "graduate", label: "Graduate visa" },
  { value: "skilled_worker", label: "Skilled Worker" },
  { value: "dependant", label: "Dependant" },
  { value: "student", label: "Student" },
  { value: "global_talent", label: "Global Talent" },
  { value: "other", label: "Other visa" },
];

export function StageVisa({ answers, update }: StageProps) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Visa status</h2>
      <p className="text-sm text-muted-foreground">
        Used to apply UK-specific sponsor + SOC threshold checks.
      </p>
      <div className="space-y-2">
        {[
          { value: "uk_resident", label: "UK citizen / settled (ILR)" },
          { value: "visa_holder", label: "On a visa" },
        ].map((opt) => (
          <label
            key={opt.value}
            className="flex cursor-pointer items-center gap-2 text-sm"
          >
            <input
              type="radio"
              name="user_type"
              value={opt.value}
              checked={answers.user_type === opt.value}
              onChange={() =>
                update({ user_type: opt.value as OnboardingAnswers["user_type"] })
              }
            />
            {opt.label}
          </label>
        ))}
      </div>
      {answers.user_type === "visa_holder" && (
        <div className="grid gap-3 rounded-md border bg-muted/20 p-3">
          <label className="block">
            <span className="text-sm font-medium">Visa route</span>
            <select
              value={answers.visa_route}
              onChange={(e) =>
                update({ visa_route: e.target.value as OnboardingAnswers["visa_route"] })
              }
              className="mt-1 h-10 w-full rounded-md border border-input bg-white text-card-foreground px-3 text-sm font-sans"
            >
              <option value="">Select…</option>
              {VISA_ROUTES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-sm font-medium">Visa expiry</span>
            <Input
              type="date"
              value={answers.visa_expiry}
              onChange={(e) => update({ visa_expiry: e.target.value })}
              className="mt-1"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium">Nationality (optional)</span>
            <Input
              value={answers.nationality}
              onChange={(e) => update({ nationality: e.target.value })}
              placeholder="Used for grant-rate context, not stored publicly."
              className="mt-1"
            />
          </label>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 3. Money — floor + target
// ---------------------------------------------------------------------------

export function StageMoney({ answers, update }: StageProps) {
  const parse = (s: string): number | null => {
    const cleaned = s.replace(/[£,\s]/g, "");
    if (!cleaned) return null;
    const n = Number(cleaned);
    return Number.isFinite(n) ? Math.round(n) : null;
  };

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Compensation</h2>
      <p className="text-sm text-muted-foreground">
        Annual GBP. Floor = below this you won't accept. Target = what
        you're aiming for.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="text-sm font-medium">Floor</span>
          <Input
            inputMode="numeric"
            value={answers.salary_floor ?? ""}
            onChange={(e) => update({ salary_floor: parse(e.target.value) })}
            placeholder="50000"
            className="mt-1"
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium">Target (optional)</span>
          <Input
            inputMode="numeric"
            value={answers.salary_target ?? ""}
            onChange={(e) => update({ salary_target: parse(e.target.value) })}
            placeholder="75000"
            className="mt-1"
          />
        </label>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 4. Work context — employment + search duration + life constraints
// ---------------------------------------------------------------------------

export function StageWorkContext({ answers, update }: StageProps) {
  const toggleConstraint = (value: string) => {
    const next = answers.life_constraints.includes(value)
      ? answers.life_constraints.filter((c) => c !== value)
      : [...answers.life_constraints, value];
    update({ life_constraints: next });
  };

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Work context</h2>
      <p className="text-sm text-muted-foreground">
        Drives how urgent salary negotiations should be.
      </p>
      <label className="block">
        <span className="text-sm font-medium">Current employment</span>
        <select
          value={answers.current_employment}
          onChange={(e) =>
            update({
              current_employment: e.target
                .value as OnboardingAnswers["current_employment"],
            })
          }
          className="mt-1 h-10 w-full rounded-md border border-input bg-white text-card-foreground px-3 text-sm font-sans"
        >
          <option value="">Select…</option>
          <option value="EMPLOYED">Employed</option>
          <option value="NOTICE_PERIOD">On notice</option>
          <option value="UNEMPLOYED">Not working</option>
        </select>
      </label>
      <label className="block">
        <span className="text-sm font-medium">
          Searching for how many months? (optional)
        </span>
        <Input
          inputMode="numeric"
          value={answers.search_duration_months ?? ""}
          onChange={(e) => {
            const v = e.target.value.replace(/[^\d]/g, "");
            update({ search_duration_months: v ? Number(v) : null });
          }}
          placeholder="0"
          className="mt-1"
        />
      </label>
      <div>
        <p className="text-sm font-medium">Life constraints</p>
        <p className="text-xs text-muted-foreground">
          Any that apply — the verdict agent flags roles that conflict.
        </p>
        <div className="mt-2 space-y-1">
          {LIFE_CONSTRAINT_OPTIONS.map((opt) => (
            <label
              key={opt}
              className="flex cursor-pointer items-center gap-2 text-sm"
            >
              <input
                type="checkbox"
                checked={answers.life_constraints.includes(opt)}
                onChange={() => toggleConstraint(opt)}
              />
              {opt}
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 5. Motivations — free-text
// ---------------------------------------------------------------------------

export function StageMotivations({ answers, update }: StageProps) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">What drives you?</h2>
      <p className="text-sm text-muted-foreground">
        In your own words — the verdict agent scores roles against this.
        Short is fine. Plain sentences beat buzzwords.
      </p>
      <Textarea
        rows={6}
        value={answers.motivations_text}
        onChange={(e) => update({ motivations_text: e.target.value })}
        placeholder="Shipping products people actually use. Technical ownership. Teams that ship fast without cutting corners on testing."
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// 6. Deal breakers + green flags
// ---------------------------------------------------------------------------

export function StageDealBreakers({ answers, update }: StageProps) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Deal-breakers & green flags</h2>
      <div>
        <p className="text-sm font-medium">Deal-breakers</p>
        <p className="text-xs text-muted-foreground">
          Things that flip a role to NO_GO regardless of salary.
        </p>
        <Textarea
          rows={4}
          value={answers.deal_breakers_text}
          onChange={(e) => update({ deal_breakers_text: e.target.value })}
          placeholder="No remote flexibility. Maintenance-only work. Weekly all-hands with no tech track."
          className="mt-1"
        />
      </div>
      <div>
        <p className="text-sm font-medium">Green flags (optional)</p>
        <p className="text-xs text-muted-foreground">
          What makes a role jump up the list when mentioned in the JD.
        </p>
        <Textarea
          rows={4}
          value={answers.good_role_signals_text}
          onChange={(e) => update({ good_role_signals_text: e.target.value })}
          placeholder="Named tech leads writing code. Product-engineering hybrid culture. Explicit 4-day-week trials."
          className="mt-1"
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 7. Career narrative — optional free-text
// ---------------------------------------------------------------------------

export function StageCareer({ answers, update }: StageProps) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Career so far (optional)</h2>
      <p className="text-sm text-muted-foreground">
        A paragraph in your own voice. Feeds the retrievable career
        store — generators pull from it when drafting CVs.
      </p>
      <Textarea
        rows={8}
        value={answers.career_narrative}
        onChange={(e) => update({ career_narrative: e.target.value })}
        placeholder="Engineer for about 6 years. Started at a small fintech, then two years at a platform team running Kubernetes + Python services. Last role shipped the observability rewrite. Moving now for technical ownership + a visa-friendly employer."
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// 8. Writing samples — multi-textarea
// ---------------------------------------------------------------------------

export function StageSamples({ answers, update }: StageProps) {
  const setAt = (i: number, value: string) => {
    const next = [...answers.writing_samples];
    next[i] = value;
    update({ writing_samples: next });
  };
  const add = () =>
    update({ writing_samples: [...answers.writing_samples, ""] });
  const remove = (i: number) =>
    update({
      writing_samples: answers.writing_samples.filter((_, idx) => idx !== i),
    });

  const samples = answers.writing_samples.length > 0
    ? answers.writing_samples
    : [""];

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Writing samples</h2>
      <p className="text-sm text-muted-foreground">
        Paste 2–4 bits of your own writing — emails, messages, an old
        cover-letter draft, whatever sounds like you. Everything generated
        later gets run through the style extracted from these. Don't
        worry about formatting.
      </p>
      <div className="space-y-3">
        {samples.map((sample, i) => (
          <div key={i} className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">
                Sample {i + 1}
              </span>
              {answers.writing_samples.length > 1 && (
                <button
                  type="button"
                  onClick={() => remove(i)}
                  className="text-xs text-destructive hover:underline"
                >
                  Remove
                </button>
              )}
            </div>
            <Textarea
              rows={5}
              value={sample}
              onChange={(e) => setAt(i, e.target.value)}
              placeholder="Paste here."
            />
          </div>
        ))}
        <button
          type="button"
          onClick={add}
          className="text-sm underline"
        >
          + Add another sample
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stage registry — order + labels for the progress indicator
// ---------------------------------------------------------------------------

export interface StageDef {
  key: string;
  title: string;
  component: (p: StageProps) => JSX.Element;
}

export const STAGES: StageDef[] = [
  { key: "cv_upload", title: "Start from your CV", component: StageCVUpload },
  { key: "basics", title: "About you", component: StageBasics },
  { key: "visa", title: "Visa", component: StageVisa },
  { key: "money", title: "Money", component: StageMoney },
  { key: "work", title: "Work context", component: StageWorkContext },
  { key: "motivations", title: "Motivations", component: StageMotivations },
  { key: "deal_breakers", title: "Deal-breakers", component: StageDealBreakers },
  { key: "career", title: "Career", component: StageCareer },
  { key: "samples", title: "Samples", component: StageSamples },
];
