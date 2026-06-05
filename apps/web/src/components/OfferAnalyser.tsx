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
import { AlertTriangle, FileUp, Flag, Loader2, Receipt, ShieldCheck, TrendingUp } from "lucide-react";

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
    <Card className={cn("border-canvas bg-card/40 overflow-hidden relative group shadow-2xl", className)}>
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary/20 via-primary/50 to-primary/20" />
      <CardHeader className="pb-3 border-b border-canvas bg-secondary/20">
        <CardTitle className="flex items-center gap-3 font-serif text-lg tracking-tight">
          <div className="p-1.5 rounded bg-background border border-canvas shadow-inner">
            <Receipt className="h-4 w-4 text-primary" />
          </div>
          Offer Auditor
        </CardTitle>
        <div className="flex items-center gap-2 mt-1">
          <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
          <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">
            {sessionId ? "Context-Aware Comparison" : "Standalone Forensic Mode"}
          </p>
        </div>
      </CardHeader>
      <CardContent className="pt-6 space-y-6">
        {analysis === null && (
          <form className="space-y-6" onSubmit={onSubmit}>
            <div className="space-y-3">
              <label className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground flex items-center gap-2">
                <FileUp className="h-3 w-3" />
                Upload Evidence (PDF)
              </label>
              <div className="flex items-center gap-3">
                <label
                  htmlFor="offer-pdf"
                  className={cn(
                    "flex-1 flex items-center gap-3 rounded-2xl border-2 border-dashed px-4 py-6 text-sm cursor-pointer transition-all duration-300",
                    pdf 
                      ? "border-success/40 bg-success/5 text-success" 
                      : "border-canvas bg-background/50 hover:bg-background hover:border-primary/30 text-muted-foreground",
                  )}
                >
                  <div className={cn("p-2 rounded-lg", pdf ? "bg-success/20" : "bg-secondary")}>
                    <FileUp className="h-5 w-5" />
                  </div>
                  <div className="flex flex-col">
                    <span className="font-bold">{pdf ? pdf.name : "Select Offer Document"}</span>
                    <span className="text-[10px] opacity-60 font-mono">PDF preferred for page-level citations</span>
                  </div>
                </label>
                <input
                  id="offer-pdf"
                  type="file"
                  accept="application/pdf,.pdf"
                  className="hidden"
                  onChange={(e) => setPdf(e.target.files?.[0] ?? null)}
                />
              </div>
            </div>

            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-canvas" />
              </div>
              <div className="relative flex justify-center">
                <span className="bg-card px-3 text-[10px] font-mono text-muted-foreground uppercase tracking-widest">Manual Ingest</span>
              </div>
            </div>

            <div className="space-y-3">
              <label className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
                Raw Text Dump
              </label>
              <textarea
                className="w-full rounded-2xl border border-canvas bg-background/50 px-4 py-3 text-sm min-h-[140px] font-mono transition-all focus:bg-background focus:ring-1 focus:ring-primary/30"
                placeholder="Paste offer body or email excerpt..."
                value={text}
                onChange={(e) => setText(e.target.value)}
                disabled={pdf !== null}
              />
            </div>

            <div className="space-y-4 pt-2">
              <Button
                type="submit"
                disabled={!canSubmit || status === "running"}
                className="w-full h-12 font-bold uppercase tracking-widest text-[10px]"
              >
                {status === "running" ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Auditing Archive...
                  </>
                ) : (
                  "[ RUN OFFER AUDIT ]"
                )}
              </Button>
              {error && (
                <div className="p-3 rounded-xl border border-destructive/20 bg-destructive/5 text-[11px] font-mono text-destructive text-center">
                  <span className="font-bold">FAULT:</span> {error}
                </div>
              )}
            </div>
          </form>
        )}

        {status === "running" && analysis === null && (
          <div className="flex flex-col items-center justify-center py-12 space-y-4 animate-pulse">
            <div className="relative">
              <div className="h-16 w-16 rounded-full border-4 border-primary/20 border-t-primary animate-spin" />
              <Receipt className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 h-6 w-6 text-primary" />
            </div>
            <div className="text-center space-y-1">
                <p className="font-serif text-lg tracking-tight">Synthesizing Clauses</p>
                <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">Cross-referencing market datasets</p>
            </div>
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
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex items-start justify-between gap-4 p-4 rounded-2xl bg-secondary/30 border border-canvas shadow-inner">
        <div className="space-y-1">
          <h3 className="text-xl font-serif tracking-tight leading-none">{analysis.company_name}</h3>
          {analysis.role_title && (
            <div className="flex items-center gap-2">
                <div className="h-px w-3 bg-primary/40" />
                <p className="text-[11px] font-mono text-muted-foreground uppercase tracking-widest">{analysis.role_title}</p>
            </div>
          )}
        </div>
        <Button variant="outline" size="sm" onClick={onReset} className="text-[9px] font-bold uppercase tracking-widest h-7 px-2">
          NEW AUDIT
        </Button>
      </div>

      {analysis.flags.length > 0 && (
        <div className="rounded-2xl border border-destructive/20 bg-destructive/5 p-4 space-y-3 relative overflow-hidden group">
          <div className="absolute top-0 left-0 w-1 h-full bg-destructive/30 group-hover:bg-destructive transition-colors" />
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-destructive flex items-center gap-2">
            <Flag className="h-3 w-3" />
            Advisory Warnings
          </p>
          <ul className="space-y-2">
            {analysis.flags.map((f, i) => (
              <li key={i} className="text-[11px] flex gap-2 items-start leading-relaxed font-medium">
                <span className="text-destructive font-bold select-none mt-0.5 opacity-50">›</span>
                {f}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="space-y-2">
        <p className="text-[9px] font-bold uppercase tracking-[0.3em] text-muted-foreground px-1">Valuation Breakdown</p>
        <div className="p-4 rounded-2xl bg-background/40 border border-canvas space-y-3 shadow-inner">
            <ComponentRow label="Base Salary" comp={analysis.base_salary_gbp} isPrimary />
            <ComponentRow label="Bonus Target" comp={analysis.bonus} />
            <ComponentRow label="Equity Package" comp={analysis.equity} />
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-[9px] font-bold uppercase tracking-[0.3em] text-muted-foreground px-1">Contractual Analysis</p>
        <div className="p-4 rounded-2xl bg-background/40 border border-canvas space-y-3 shadow-inner">
            <ComponentRow label="Notice Period" comp={analysis.notice_period} />
            <ComponentRow label="Non-Compete" comp={analysis.non_compete} />
            <ComponentRow label="IP Assignment" comp={analysis.ip_assignment} />
        </div>
      </div>

      {analysis.benefits.length > 0 && (
        <div className="space-y-2">
            <p className="text-[9px] font-bold uppercase tracking-[0.3em] text-muted-foreground px-1 flex items-center gap-2">
                <ShieldCheck className="h-3 w-3 text-success/60" />
                Benefits Registry
            </p>
            <div className="flex flex-wrap gap-2 p-1">
                {analysis.benefits.map((c, i) => (
                    <div key={i} className="px-2.5 py-1.5 rounded-lg bg-secondary/50 border border-canvas text-[11px] flex items-center gap-2 group/ben hover:border-primary/30 transition-colors">
                        <span className="leading-none">{c.value_text}</span>
                        <CitationBadge comp={c} className="scale-75 origin-right opacity-0 group-hover/ben:opacity-100 transition-opacity" />
                    </div>
                ))}
            </div>
        </div>
      )}

      {analysis.unusual_clauses.length > 0 && (
        <div className="space-y-3">
          <p className="text-[9px] font-bold uppercase tracking-[0.3em] text-muted-foreground px-1 flex items-center gap-2">
            <AlertTriangle className="h-3 w-3 text-warning" />
            Anomalous Clauses Detected
          </p>
          <div className="space-y-2">
            {analysis.unusual_clauses.map((c, i) => (
              <div key={i} className="p-3 rounded-xl border border-warning/20 bg-warning/5 space-y-1 relative group/clause">
                <div className="flex justify-between items-start gap-4">
                    <span className="text-[10px] font-bold uppercase text-warning tracking-tighter">{c.label}</span>
                    <CitationBadge comp={c} className="scale-90" />
                </div>
                <p className="text-[11px] leading-relaxed font-medium">{c.value_text}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {analysis.market_comparison_note && (
        <div className="rounded-2xl border border-primary/20 bg-primary/5 p-4 space-y-3 relative group overflow-hidden">
          <div className="absolute top-0 right-0 p-2 opacity-5">
             <TrendingUp className="h-16 w-16" />
          </div>
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-primary flex items-center gap-2">
            <TrendingUp className="h-3 w-3" />
            Market Benchmarking
          </p>
          <p className="text-xs leading-relaxed text-muted-foreground relative z-10">{analysis.market_comparison_note}</p>
        </div>
      )}
    </div>
  );
}

function ComponentRow({
  label,
  comp,
  isPrimary = false,
}: {
  label: string;
  comp: OfferComponent | null;
  isPrimary?: boolean;
}) {
  if (!comp) return null;
  return (
    <div className="flex items-center justify-between gap-4 py-1 first:pt-0 last:pb-0 group/row">
      <div className="flex items-center gap-3">
          <div className={cn("w-1 h-1 rounded-full bg-canvas group-hover/row:bg-primary/50 transition-colors", isPrimary && "bg-primary/40")} />
          <span className={cn("text-[11px] font-bold uppercase tracking-widest text-muted-foreground", isPrimary && "text-foreground")}>{label}</span>
      </div>
      <div className="flex items-center gap-3">
        <span className={cn("text-[11px] font-mono font-bold tracking-tight", isPrimary && "text-lg text-primary tracking-tighter")}>
          {comp.value_text}
        </span>
        <CitationBadge comp={comp} className="scale-90 opacity-40 group-hover/row:opacity-100 transition-opacity" />
      </div>
    </div>
  );
}

function CitationBadge({ comp, className }: { comp: OfferComponent; className?: string }) {
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
      className={cn("px-1.5 py-0 rounded-sm font-mono text-[9px] uppercase tracking-tighter h-4 border-canvas bg-secondary/30 text-muted-foreground cursor-help", className)}
      title={tip}
    >
      {c.kind === "url_snippet" ? "cited" : c.kind === "gov_data" ? "gov" : "entry"}
    </Badge>
  );
}
