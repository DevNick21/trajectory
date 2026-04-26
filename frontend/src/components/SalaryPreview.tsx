import { AlertTriangle, Loader2, Sparkles } from "lucide-react";

import type { SalaryRecommendation } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Props {
  output: SalaryRecommendation | null;
  generating: boolean;
  error: string | null;
  onGenerate: () => void;
}

export default function SalaryPreview({
  output,
  generating,
  error,
  onGenerate,
}: Props) {
  return (
    <Card className="min-h-[28rem]">
      <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0">
        <CardTitle>Salary negotiation strategy</CardTitle>
        {output && (
          <Button
            variant="outline"
            size="sm"
            onClick={onGenerate}
            disabled={generating}
          >
            {generating ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Regenerating
              </>
            ) : (
              "Regenerate"
            )}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {!output && !generating && (
          <Empty onGenerate={onGenerate} error={error} />
        )}
        {generating && !output && <Generating />}
        {output && <Strategy s={output} />}
        {output && error && (
          <p className="mt-4 text-xs text-destructive">{error}</p>
        )}
      </CardContent>
    </Card>
  );
}

function Empty({
  onGenerate,
  error,
}: {
  onGenerate: () => void;
  error: string | null;
}) {
  return (
    <div className="flex min-h-[20rem] flex-col items-center justify-center gap-3 text-center">
      <Sparkles className="h-8 w-8 text-primary" aria-hidden />
      <div>
        <p className="text-sm font-medium">No salary strategy yet</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Opening number, floor, ceiling — grounded in market data and your
          urgency.
        </p>
      </div>
      <Button onClick={onGenerate}>
        <Sparkles className="mr-2 h-4 w-4" />
        Generate strategy
      </Button>
      {error && (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function Generating() {
  return (
    <div className="flex min-h-[20rem] flex-col items-center justify-center gap-3 text-center">
      <Loader2 className="h-8 w-8 animate-spin text-primary" aria-hidden />
      <p className="text-sm text-muted-foreground">Building your strategy…</p>
    </div>
  );
}

function Strategy({ s }: { s: SalaryRecommendation }) {
  const fmt = (n: number) => `£${n.toLocaleString()}`;
  return (
    <article className="space-y-6 text-card-foreground">
      {/* Headline numbers */}
      <section className="grid grid-cols-3 gap-3">
        <Stat label="Floor" value={fmt(s.floor)} muted />
        <Stat label="Opening" value={fmt(s.opening_number)} highlighted />
        <Stat label="Ceiling" value={fmt(s.ceiling)} muted />
      </section>

      {/* Confidence + sponsor flag */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant={s.confidence === "HIGH" ? "success" : "secondary"}>
          Confidence · {s.confidence}
        </Badge>
        {s.sponsor_constraint_active && (
          <Badge variant="secondary">SOC sponsor floor active</Badge>
        )}
      </div>

      {/* Opening phrasing */}
      <section>
        <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Opening line
        </h3>
        <p className="rounded-md border bg-muted/50 p-3 text-sm italic">
          &ldquo;{s.opening_phrasing}&rdquo;
        </p>
      </section>

      {/* Urgency note (only when present) */}
      {s.urgency_note && (
        <section className="rounded-md border border-primary/30 bg-accent p-3 text-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-accent-foreground">
            Urgency
          </p>
          <p className="mt-1 text-accent-foreground">{s.urgency_note}</p>
        </section>
      )}

      {/* Reasoning */}
      {s.reasoning.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Reasoning
          </h3>
          <ul className="space-y-2">
            {s.reasoning.map((r, i) => (
              <li
                key={i}
                className="rounded-md border p-3 text-sm leading-relaxed"
              >
                <p className="font-medium">{r.claim}</p>
                <p className="mt-1 text-muted-foreground">
                  {r.supporting_evidence}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Scripts */}
      {Object.keys(s.scripts).length > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Scripts
          </h3>
          <div className="space-y-2">
            {Object.entries(s.scripts).map(([situation, script]) => (
              <div key={situation} className="rounded-md border p-3 text-sm">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {situation.replace(/_/g, " ")}
                </p>
                <p className="mt-1 leading-relaxed">{script}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Data gaps */}
      {s.data_gaps.length > 0 && (
        <section className="rounded-md border border-amber-500/40 bg-amber-50/50 p-3 text-sm">
          <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-amber-700">
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
            Data gaps
          </p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-amber-800">
            {s.data_gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}

function Stat({
  label,
  value,
  highlighted,
  muted,
}: {
  label: string;
  value: string;
  highlighted?: boolean;
  muted?: boolean;
}) {
  return (
    <div
      className={
        highlighted
          ? "rounded-md border border-primary/40 bg-accent p-3 text-center"
          : muted
            ? "rounded-md border p-3 text-center"
            : "rounded-md border p-3 text-center"
      }
    >
      <p className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 text-xl font-bold tabular-nums">{value}</p>
    </div>
  );
}
