// Eight wizard stages, rendered one at a time by OnboardingWizard.
// Each stage is a small form that reads + writes via the shared
// OnboardingAnswers object from the useOnboardingDraft hook. No
// per-stage validation beyond "required fields filled" — that
// happens in validateForFinalise at submit time.

import type { OnboardingAnswers } from "@/lib/types";
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
              className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
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
          className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
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
  { key: "basics", title: "About you", component: StageBasics },
  { key: "visa", title: "Visa", component: StageVisa },
  { key: "money", title: "Money", component: StageMoney },
  { key: "work", title: "Work context", component: StageWorkContext },
  { key: "motivations", title: "Motivations", component: StageMotivations },
  { key: "deal_breakers", title: "Deal-breakers", component: StageDealBreakers },
  { key: "career", title: "Career", component: StageCareer },
  { key: "samples", title: "Samples", component: StageSamples },
];
