// OfferAnalyser — frontend surface for the analyse_offer pipeline
// (PROCESS Entry 43, Workstream F). Two input modes:
//   1. Upload a PDF of the offer letter (preferred — Citations API
//      attaches every claim to a page)
//   2. Paste plain text (fallback for emails / inline offers)
//
// `sessionId` (optional) ties the analysis to the most-recent
// ResearchBundle for richer market comparison via gov-data citations.
// Standalone use (no session) works too — just no comparison flags.

import { useState } from "react";
import { AlertTriangle, FileUp, Flag, Loader2, Receipt } from "lucide-react";

import { ApiError, analyseOffer } from "@/lib/api";
import type { OfferAnalysis, OfferComponent } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface Props {
  sessionId?: string;          // optional — bundle-aware comparison when present
  className?: string;
}

type Status = "idle" | "running" | "complete" | "failed";

export default function OfferAnalyser({ sessionId, className }: Props) {
  const [pdf, setPdf] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<OfferAnalysis | null>(null);

  const canSubmit = (pdf !== null) || text.trim().length > 0;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setStatus("running");
    setError(null);
    setAnalysis(null);
    try {
      const resp = await analyseOffer({
        sessionId,
        pdf: pdf ?? undefined,
        text: text.trim() ? text : undefined,
      });
      setAnalysis(resp.output);
      setStatus("complete");
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message
        : err instanceof Error ? err.message
        : "Offer analysis failed.";
      setError(message);
      setStatus("failed");
    }
  };

  const reset = () => {
    setPdf(null);
    setText("");
    setAnalysis(null);
    setError(null);
    setStatus("idle");
  };

  return (
    <Card className={cn("space-y-0", className)}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Receipt className="h-4 w-4" />
          Offer letter analyser
        </CardTitle>
        {sessionId
          ? <p className="text-xs text-muted-foreground">
              Comparing against the research bundle on this session.
            </p>
          : <p className="text-xs text-muted-foreground">
              Standalone analysis — no market-comparison flags. Pick a session for richer output.
            </p>
        }
      </CardHeader>
      <CardContent className="space-y-4">
        {analysis === null && (
          <form className="space-y-4" onSubmit={onSubmit}>
            <div>
              <label className="text-sm font-medium block mb-1">
                Upload offer PDF
              </label>
              <div className="flex items-center gap-2">
                <label
                  htmlFor="offer-pdf"
                  className={cn(
                    "inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm cursor-pointer hover:bg-secondary/40",
                    pdf && "border-success/60 bg-success/5",
                  )}
                >
                  <FileUp className="h-4 w-4" />
                  {pdf ? pdf.name : "Choose PDF…"}
                </label>
                <input
                  id="offer-pdf"
                  type="file"
                  accept="application/pdf,.pdf"
                  className="hidden"
                  onChange={(e) => setPdf(e.target.files?.[0] ?? null)}
                />
                {pdf && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setPdf(null)}
                  >
                    Clear
                  </Button>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                Citations API will attach every claim to a page.
              </p>
            </div>

            <div className="text-center text-xs text-muted-foreground">— OR —</div>

            <div>
              <label className="text-sm font-medium block mb-1">
                Paste offer text
              </label>
              <textarea
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm min-h-[140px] font-mono"
                placeholder="Paste the offer letter (or excerpt) here…"
                value={text}
                onChange={(e) => setText(e.target.value)}
                disabled={pdf !== null}
              />
            </div>

            <div className="flex gap-2 pt-2">
              <Button
                type="submit"
                disabled={!canSubmit || status === "running"}
              >
                {status === "running" && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Analyse offer
              </Button>
              {error && (
                <p className="text-sm text-destructive self-center">{error}</p>
              )}
            </div>
          </form>
        )}

        {status === "running" && analysis === null && (
          <div className="rounded-md border bg-secondary/30 p-3 text-sm flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            Analysing offer… ~30-60s for a typical PDF.
          </div>
        )}

        {analysis && (
          <OfferReport analysis={analysis} onReset={reset} />
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Report rendering
// ---------------------------------------------------------------------------

function OfferReport({
  analysis,
  onReset,
}: {
  analysis: OfferAnalysis;
  onReset: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold">{analysis.company_name}</h3>
          {analysis.role_title && (
            <p className="text-sm text-muted-foreground">{analysis.role_title}</p>
          )}
        </div>
        <Button variant="outline" size="sm" onClick={onReset}>
          Analyse another
        </Button>
      </div>

      {analysis.flags.length > 0 && (
        <div className="rounded-md border border-destructive/50 bg-destructive/5 p-3 space-y-1">
          <p className="text-sm font-medium flex items-center gap-2">
            <Flag className="h-4 w-4 text-destructive" />
            Flags
          </p>
          <ul className="text-sm space-y-0.5">
            {analysis.flags.map((f, i) => (
              <li key={i} className="text-destructive">• {f}</li>
            ))}
          </ul>
        </div>
      )}

      <ComponentRow label="Base salary" comp={analysis.base_salary_gbp} />
      <ComponentRow label="Bonus" comp={analysis.bonus} />
      <ComponentRow label="Equity" comp={analysis.equity} />
      <ComponentRow label="Notice period" comp={analysis.notice_period} />
      <ComponentRow label="Non-compete" comp={analysis.non_compete} />
      <ComponentRow label="IP assignment" comp={analysis.ip_assignment} />

      {analysis.benefits.length > 0 && (
        <ComponentList label="Benefits" items={analysis.benefits} />
      )}

      {analysis.unusual_clauses.length > 0 && (
        <div className="space-y-1">
          <p className="text-sm font-medium flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-600" />
            Unusual clauses
          </p>
          <ul className="text-sm space-y-1">
            {analysis.unusual_clauses.map((c, i) => (
              <li key={i} className="rounded-md border bg-amber-50 px-2 py-1">
                <span className="font-medium">{c.label}:</span> {c.value_text}
                <CitationBadge comp={c} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {analysis.market_comparison_note && (
        <div className="rounded-md border bg-secondary/30 p-3">
          <p className="text-sm font-medium mb-1">Market comparison</p>
          <p className="text-sm">{analysis.market_comparison_note}</p>
        </div>
      )}
    </div>
  );
}

function ComponentRow({
  label,
  comp,
}: {
  label: string;
  comp: OfferComponent | null;
}) {
  if (!comp) return null;
  return (
    <div className="flex items-baseline justify-between gap-3 border-b pb-2 last:border-b-0">
      <span className="text-sm font-medium text-muted-foreground">{label}</span>
      <span className="text-sm text-right">
        {comp.value_text}
        <CitationBadge comp={comp} />
      </span>
    </div>
  );
}

function ComponentList({
  label,
  items,
}: {
  label: string;
  items: OfferComponent[];
}) {
  return (
    <div className="space-y-1">
      <p className="text-sm font-medium">{label}</p>
      <ul className="text-sm space-y-0.5">
        {items.map((c, i) => (
          <li key={i} className="flex items-baseline justify-between gap-3">
            <span>• {c.value_text}</span>
            <CitationBadge comp={c} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function CitationBadge({ comp }: { comp: OfferComponent }) {
  const c = comp.citation;
  let tip: string;
  if (c.kind === "url_snippet") {
    tip = c.verbatim_snippet ?? c.url ?? "cited";
  } else if (c.kind === "gov_data") {
    tip = `${c.data_field} = ${c.data_value}`;
  } else {
    tip = `entry: ${c.entry_id}`;
  }
  return (
    <Badge
      variant="outline"
      className="ml-2 text-[10px] font-normal align-middle"
      title={tip}
    >
      {c.kind === "url_snippet" ? "cited" : c.kind === "gov_data" ? "gov" : "entry"}
    </Badge>
  );
}
