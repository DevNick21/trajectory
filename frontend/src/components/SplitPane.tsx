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
    <div className="grid gap-8 lg:grid-cols-[minmax(0,25%)_minmax(0,1fr)]">
      <div className="flex flex-col gap-6 overflow-hidden">
        <ContextCard bundle={bundle} />
        <div className="flex-1 overflow-hidden">
          <CareerHistory
            highlightedEntryIds={highlightedEntryIds ?? new Set<string>()}
            scrollKey={scrollKey ?? null}
          />
        </div>
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

function ContextCard({ bundle }: { bundle: ContextBundle | null }) {
  const jd = bundle?.extracted_jd;
  const cr = bundle?.company_research;

  if (!jd && !cr) {
    return (
      <Card className="bg-destructive/5 border-destructive/20">
        <CardHeader className="py-3">
          <CardTitle className="text-[10px] font-bold uppercase tracking-widest text-destructive">Signal Lost</CardTitle>
        </CardHeader>
        <CardContent className="text-xs text-muted-foreground italic">
          No research bundle detected.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-secondary/30 border-canvas overflow-hidden">
      <CardHeader className="py-3 bg-secondary/50 border-b border-canvas">
        <CardTitle className="text-[10px] font-bold uppercase tracking-[0.2em] text-primary flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-primary" />
          Target Parameters
        </CardTitle>
      </CardHeader>
      <CardContent className="p-4 space-y-4 text-xs">
        {jd?.role_title && (
          <Field label="Designation" hint={jd.seniority_signal?.toUpperCase()}>
            <span className="font-serif text-lg tracking-tight">{jd.role_title}</span>
          </Field>
        )}
        {cr?.company_name && (
          <Field label="Entity" hint={cr.company_domain ?? undefined}>
             <span className="font-mono">{cr.company_name}</span>
          </Field>
        )}
        {jd?.location && (
          <Field label="Geographic Range">
            {jd.location}
            {jd.remote_policy && (
              <span className="text-primary font-bold"> · {jd.remote_policy}</span>
            )}
          </Field>
        )}
        {jd?.salary_band && (
          <Field label="Market Valuation">
            <span className="font-mono text-success font-bold">
              £{jd.salary_band.min_gbp?.toLocaleString()}–£
              {jd.salary_band.max_gbp?.toLocaleString()}
            </span>
          </Field>
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
    <div className="space-y-1">
      <p className="text-[9px] uppercase tracking-widest text-muted-foreground font-bold">
        {label}
      </p>
      <div className="text-sm font-medium leading-tight">{children}</div>
      {hint && <p className="text-[10px] font-mono opacity-50 uppercase">{hint}</p>}
    </div>
  );
}
