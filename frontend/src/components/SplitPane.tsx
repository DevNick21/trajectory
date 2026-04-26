import type { ReactNode } from "react";

import CareerHistory from "@/components/CareerHistory";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// Slim view over the loose research_bundle JSON. Matches what
// VerdictEvidence reads, but only what the Context column needs.
export interface ContextBundle {
  extracted_jd?: {
    role_title?: string;
    location?: string;
    remote_policy?: string;
    seniority_signal?: string;
    salary_band?: { min_gbp?: number; max_gbp?: number; period?: string } | null;
    required_skills?: string[];
  };
  company_research?: {
    company_name?: string;
    company_domain?: string | null;
  };
}

interface Props {
  bundle: ContextBundle | null;
  /** Career-entry IDs to ring on the left. Empty set when the deep
   *  view doesn't drive cross-pane highlighting (cover letter,
   *  salary, questions). */
  highlightedEntryIds?: Set<string>;
  /** Entry id to scroll to. Optional — mirrors highlightedEntryIds[0]
   *  when used. */
  scrollKey?: string | null;
  /** The deep view's right-pane content. */
  children: ReactNode;
}

/** Shared 30/70 split-pane shell for every Deep Work view. Hosts the
 *  Context card + Career History on the left; consumers render the
 *  artifact-specific viewer as children on the right. */
export default function SplitPane({
  bundle,
  highlightedEntryIds,
  scrollKey,
  children,
}: Props) {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,30%)_minmax(0,1fr)]">
      <div className="flex flex-col gap-4">
        <ContextCard bundle={bundle} />
        <CareerHistory
          highlightedEntryIds={highlightedEntryIds ?? new Set<string>()}
          scrollKey={scrollKey ?? null}
        />
      </div>
      <div>{children}</div>
    </div>
  );
}

function ContextCard({ bundle }: { bundle: ContextBundle | null }) {
  const jd = bundle?.extracted_jd;
  const cr = bundle?.company_research;

  if (!jd && !cr) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Context</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          No research bundle on this session.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Context</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {jd?.role_title && (
          <Field label="Role" hint={jd.seniority_signal}>
            {jd.role_title}
          </Field>
        )}
        {cr?.company_name && (
          <Field label="Company" hint={cr.company_domain ?? undefined}>
            {cr.company_name}
          </Field>
        )}
        {jd?.location && (
          <Field label="Location">
            {jd.location}
            {jd.remote_policy && (
              <span className="text-muted-foreground"> · {jd.remote_policy}</span>
            )}
          </Field>
        )}
        {jd?.salary_band && (
          <Field label="Posted band">
            <span className="tabular-nums">
              £{jd.salary_band.min_gbp?.toLocaleString()}–£
              {jd.salary_band.max_gbp?.toLocaleString()}
            </span>
          </Field>
        )}
        {jd?.required_skills && jd.required_skills.length > 0 && (
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Required skills
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              {jd.required_skills.slice(0, 12).map((s) => (
                <span
                  key={s}
                  className="rounded-md bg-secondary px-2 py-0.5 text-xs text-secondary-foreground"
                >
                  {s}
                </span>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string | null;
  children: ReactNode;
}) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="font-medium">{children}</p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
