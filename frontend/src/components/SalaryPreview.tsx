import { Loader2, Terminal } from "lucide-react";
import PickyAvatar from "@/components/PickyAvatar";

import type { SalaryRecommendation } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

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
    <Card className="min-h-[28rem] bg-card border-canvas shadow-2xl overflow-hidden relative group flex flex-col">
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary/40 via-success/40 to-primary/40 opacity-0 group-hover:opacity-100 transition-opacity" />
      <div className="absolute inset-0 bg-grid-white/[0.01] bg-[size:30px_30px] pointer-events-none" />

      <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0 border-b border-canvas bg-secondary/10 relative z-10 py-3">
        <div className="flex items-center gap-3">
          <div className="p-1.5 rounded bg-background border border-canvas shadow-inner">
            <Terminal className="h-3.5 w-3.5 text-primary" />
          </div>
          <div className="flex flex-col">
            <CardTitle className="text-[10px] font-mono font-bold uppercase tracking-[0.2em] text-muted-foreground leading-none">Salary Advice</CardTitle>
            <span className="text-[8px] font-mono text-primary/50 uppercase tracking-widest mt-1">Based on Market Data</span>
          </div>
        </div>
        {output && (
          <Button
            variant="outline"
            size="sm"
            onClick={onGenerate}
            disabled={generating}
            className="h-7 text-[9px] font-mono uppercase tracking-widest border-primary/20 hover:border-primary/50 hover:bg-primary/5"
          >
            {generating ? (
              <>
                <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                Regenerating
              </>
            ) : (
              "[ Re-Synthesize ]"
            )}
          </Button>
        )}
      </CardHeader>
      <CardContent className="flex-1 relative z-10 overflow-auto pt-4">
        {!output && !generating && (
          <Empty onGenerate={onGenerate} error={error} />
        )}
        {generating && !output && <Generating />}
        {output && <Strategy s={output} />}
        {output && error && (
          <div className="mt-4 p-3 rounded border border-destructive/20 bg-destructive/5 flex gap-3 items-center">
            <div className="w-1.5 h-1.5 rounded-full bg-destructive animate-pulse" />
            <p className="text-[10px] text-destructive font-mono uppercase tracking-tight">ERROR: {error}</p>
          </div>
        )}
      </CardContent>

      {/* Forensic Footer */}
      <div className="border-t border-canvas bg-secondary/5 px-4 py-2 flex items-center justify-between relative z-10">
        <div className="flex gap-4">
          <div className="flex items-center gap-1.5">
             <div className="w-1 h-1 rounded-full bg-success" />
             <span className="text-[8px] font-mono text-muted-foreground uppercase tracking-widest">ASHE Data: Link OK</span>
          </div>
          <div className="flex items-center gap-1.5">
             <div className="w-1 h-1 rounded-full bg-success" />
             <span className="text-[8px] font-mono text-muted-foreground uppercase tracking-widest">SOC Correlation: 1.0</span>
          </div>
        </div>
        <span className="text-[8px] font-mono text-muted-foreground/30 uppercase tracking-tighter">LAB-SIG: SAL-{Math.random().toString(36).substring(7).toUpperCase()}</span>
      </div>
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
    <div className="flex min-h-[22rem] flex-col items-center justify-center gap-6 text-center py-12">
      <div className="relative">
        <PickyAvatar state="idle" className="h-24 w-24" />
        <div className="absolute inset-0 blur-2xl bg-primary/10 rounded-full -z-10" />
      </div>
      <div className="max-w-xs space-y-3">
        <p className="font-serif text-xl tracking-tight italic">"Waiting for my orders."</p>
        <p className="text-[11px] text-muted-foreground leading-relaxed font-mono uppercase tracking-tight opacity-70">
          I'll build a negotiation strategy based on ASHE market data, company financials, and your specific urgency profile.
        </p>
      </div>
      <Button 
        onClick={onGenerate}
        className="font-bold uppercase tracking-[0.2em] text-[10px] px-10 h-11 bg-primary text-primary-foreground hover:bg-primary/90 shadow-lg shadow-primary/20"
      >
        [ Build Strategy ]
      </Button>
      {error && (
        <div className="mt-4 p-3 rounded border border-destructive/20 bg-destructive/5 flex gap-3 items-center">
          <div className="w-1.5 h-1.5 rounded-full bg-destructive animate-pulse" />
          <p className="text-[10px] text-destructive font-mono uppercase tracking-tight">System Fault: {error}</p>
        </div>
      )}
    </div>
  );
}

function Generating() {
  return (
    <div className="flex min-h-[22rem] flex-col items-center justify-center gap-8 text-center py-12 relative overflow-hidden">
      <PickyAvatar state="thinking" className="h-24 w-24 z-10" />
      <div className="space-y-4 z-10">
        <div className="flex flex-col items-center gap-1">
          <p className="font-serif text-2xl tracking-tighter italic animate-pulse">"Running market analysis..."</p>
          <div className="w-24 h-0.5 bg-primary/20 relative overflow-hidden rounded-full">
            <div className="absolute top-0 left-0 h-full bg-primary w-1/2 animate-shimmer" />
          </div>
        </div>
        <div className="flex flex-col gap-1">
           <p className="text-[9px] font-mono text-primary uppercase tracking-[0.3em] font-bold">
            Correlating SOC codes
          </p>
          <p className="text-[8px] font-mono text-muted-foreground uppercase tracking-widest opacity-50">
            Scanning regional ASHE datasets · analyzing company liquidity
          </p>
        </div>
      </div>
    </div>
  );
}

function Strategy({ s }: { s: SalaryRecommendation }) {
  const fmt = (n: number) => `£${n.toLocaleString()}`;
  return (
    <article className="space-y-10 text-card-foreground p-4 bg-background/30 rounded-2xl border border-canvas shadow-inner relative overflow-hidden">
      <div className="absolute top-0 right-0 p-4 opacity-[0.02] pointer-events-none">
        <Terminal className="h-48 w-48 -rotate-12" />
      </div>

      <header className="border-b-2 border-primary/20 pb-6 relative">
        <div className="flex flex-col gap-1">
          <span className="text-[10px] font-mono text-primary font-bold uppercase tracking-[0.4em]">Target Comps</span>
          <div className="grid grid-cols-3 gap-4 mt-4">
             <Stat label="Floor" value={fmt(s.floor)} />
             <Stat label="Opening Anchor" value={fmt(s.opening_number)} highlighted />
             <Stat label="Ceiling" value={fmt(s.ceiling)} />
          </div>
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        <div className={cn(
          "flex items-center gap-2 px-3 py-1.5 rounded-lg border font-mono text-[10px] font-bold uppercase tracking-widest",
          s.confidence === "HIGH" ? "bg-success/10 border-success/30 text-success" : "bg-secondary border-canvas text-muted-foreground"
        )}>
          <div className={cn("w-1.5 h-1.5 rounded-full", s.confidence === "HIGH" ? "bg-success animate-pulse" : "bg-muted-foreground/30")} />
          Data Confidence: {s.confidence}
        </div>
        {s.sponsor_constraint_active && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-primary/30 text-primary bg-primary/10 font-mono text-[10px] font-bold uppercase tracking-widest">
            <Terminal className="h-3 w-3" />
            Sponsor Floor Applied
          </div>
        )}
      </div>

      <section className="space-y-4">
        <div className="flex items-center gap-4">
           <h3 className="text-[10px] font-mono font-bold uppercase tracking-[0.3em] text-primary whitespace-nowrap">
              Primary Phrasing
           </h3>
           <div className="h-px bg-canvas flex-1" />
        </div>
        <div className="p-6 bg-secondary/20 rounded-2xl border border-canvas relative group/phrasing">
           <div className="absolute top-0 left-0 w-1 h-full bg-primary/20 group-hover/phrasing:bg-primary transition-colors" />
           <p className="font-serif text-xl italic leading-relaxed text-foreground">
              &ldquo;{s.opening_phrasing}&rdquo;
           </p>
        </div>
      </section>

      {s.urgency_note && (
        <section className="rounded-2xl border border-primary/20 bg-primary/5 p-5 space-y-3 shadow-inner">
          <div className="flex items-center gap-2">
             <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
             <p className="text-[10px] font-mono font-bold uppercase tracking-[0.2em] text-primary">
               Urgency Calibration Active
             </p>
          </div>
          <p className="text-xs leading-relaxed text-muted-foreground font-medium italic">{s.urgency_note}</p>
        </section>
      )}

      {Object.keys(s.scripts).length > 0 && (
        <section className="space-y-6">
          <div className="flex items-center gap-4">
             <h3 className="text-[10px] font-mono font-bold uppercase tracking-[0.3em] text-primary whitespace-nowrap">
                Negotiation Scripts
             </h3>
             <div className="h-px bg-canvas flex-1" />
          </div>
          <div className="grid grid-cols-1 gap-3">
            {Object.entries(s.scripts).map(([situation, script]) => (
              <div key={situation} className="rounded-xl border border-canvas p-4 space-y-2 bg-background/50 hover:bg-secondary/30 transition-all group/script">
                <p className="text-[9px] font-mono font-bold uppercase tracking-widest text-primary opacity-60 group-hover/script:opacity-100 transition-opacity flex items-center gap-2">
                  <div className="w-1 h-1 bg-primary/40 rounded-full" />
                  {situation.replace(/_/g, " ")}
                </p>
                <p className="text-sm leading-relaxed text-muted-foreground group-hover/script:text-foreground transition-colors">{script}</p>
              </div>
            ))}
          </div>
        </section>
      )}
    </article>
  );
}

function Stat({
  label,
  value,
  highlighted,
}: {
  label: string;
  value: string;
  highlighted?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border p-4 text-center transition-all flex flex-col gap-1.5 relative overflow-hidden",
        highlighted
          ? "border-primary/40 bg-primary/5 shadow-inner"
          : "border-canvas bg-background/50 shadow-sm"
      )}
    >
      {highlighted && <div className="absolute inset-0 bg-primary/5 animate-pulse" />}
      <p className="text-[8px] font-mono font-bold uppercase tracking-[0.2em] text-muted-foreground relative z-10">
        {label}
      </p>
      <p className={cn(
        "text-xl font-bold tabular-nums tracking-tighter relative z-10 font-mono",
        highlighted ? "text-primary" : "text-foreground"
      )}>{value}</p>
    </div>
  );
}

