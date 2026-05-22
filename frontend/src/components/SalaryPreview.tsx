import { Loader2, Terminal } from "lucide-react";
import PickyAvatar from "@/components/PickyAvatar";

import type { SalaryRecommendation } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
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
    <Card className="min-h-[28rem] bg-card border-canvas shadow-2xl overflow-hidden relative group">
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary/40 via-success/40 to-primary/40 opacity-0 group-hover:opacity-100 transition-opacity" />
      <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0 border-b border-canvas bg-secondary/30">
        <div className="flex items-center gap-2">
          <Terminal className="h-4 w-4 text-primary" />
          <CardTitle className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Draft Output</CardTitle>
        </div>
        {output && (
          <Button
            variant="outline"
            size="sm"
            onClick={onGenerate}
            disabled={generating}
            className="font-bold uppercase tracking-widest text-[10px]"
          >
            {generating ? (
              <>
                <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                Regenerating
              </>
            ) : (
              "Regenerate"
            )}
          </Button>
        )}
      </CardHeader>
      <CardContent className="pt-6">
        {!output && !generating && (
          <Empty onGenerate={onGenerate} error={error} />
        )}
        {generating && !output && <Generating />}
        {output && <Strategy s={output} />}
        {output && error && (
          <p className="mt-4 text-xs text-destructive font-mono uppercase tracking-widest">ERROR: {error}</p>
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
    <div className="flex min-h-[20rem] flex-col items-center justify-center gap-6 text-center py-12">
      <PickyAvatar state="idle" className="h-20 w-20" />
      <div className="max-w-xs">
        <p className="font-serif text-lg mb-2">"Waiting for my orders."</p>
        <p className="text-xs text-muted-foreground leading-relaxed">
          I'll build a negotiation strategy based on ASHE market data, company financials, and your specific urgency profile.
        </p>
      </div>
      <Button 
        onClick={onGenerate}
        className="font-bold uppercase tracking-widest text-[10px] px-8 h-10"
      >
        [ Build Strategy ]
      </Button>
      {error && (
        <p className="text-xs text-destructive font-mono mt-4" role="alert">
          ERROR: {error}
        </p>
      )}
    </div>
  );
}

function Generating() {
  return (
    <div className="flex min-h-[20rem] flex-col items-center justify-center gap-6 text-center py-12">
      <PickyAvatar state="thinking" className="h-20 w-20" />
      <div className="space-y-2">
        <p className="font-serif text-lg animate-pulse">"Running market analysis..."</p>
        <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">
          Correlating SOC codes with regional ASHE datasets
        </p>
      </div>
    </div>
  );
}

function Strategy({ s }: { s: SalaryRecommendation }) {
  const fmt = (n: number) => `£${n.toLocaleString()}`;
  return (
    <article className="space-y-8 text-card-foreground">
      {/* Headline numbers */}
      <section className="grid grid-cols-3 gap-4">
        <Stat label="Floor" value={fmt(s.floor)} muted />
        <Stat label="Opening" value={fmt(s.opening_number)} highlighted />
        <Stat label="Ceiling" value={fmt(s.ceiling)} muted />
      </section>

      {/* Confidence + sponsor flag */}
      <div className="flex flex-wrap items-center gap-3">
        <Badge className={cn(
          "text-[9px] font-mono font-bold uppercase tracking-widest px-2 py-0.5",
          s.confidence === "HIGH" ? "bg-success/20 text-success border-success/30" : "bg-secondary text-muted-foreground border-canvas"
        )} variant="outline">
          Confidence · {s.confidence}
        </Badge>
        {s.sponsor_constraint_active && (
          <Badge variant="outline" className="text-[9px] font-mono font-bold uppercase tracking-widest px-2 py-0.5 border-primary/30 text-primary bg-primary/5">
            SOC sponsor floor active
          </Badge>
        )}
      </div>

      {/* Opening phrasing */}
      <section className="space-y-3">
        <h3 className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
          Recommended Anchor
        </h3>
        <p className="rounded-2xl border border-canvas bg-secondary/30 p-6 font-serif text-lg italic leading-relaxed">
          &ldquo;{s.opening_phrasing}&rdquo;
        </p>
      </section>

      {/* Urgency note (only when present) */}
      {s.urgency_note && (
        <section className="rounded-2xl border border-primary/20 bg-primary/5 p-4 space-y-2">
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-primary">
            Urgency Calibration
          </p>
          <p className="text-sm leading-relaxed text-muted-foreground">{s.urgency_note}</p>
        </section>
      )}

      {/* Scripts */}
      {Object.keys(s.scripts).length > 0 && (
        <section className="space-y-4">
          <h3 className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
            Negotiation Scripts
          </h3>
          <div className="grid grid-cols-1 gap-4">
            {Object.entries(s.scripts).map(([situation, script]) => (
              <div key={situation} className="rounded-2xl border border-canvas p-4 space-y-2 hover:bg-secondary/30 transition-colors">
                <p className="text-[10px] font-mono font-bold uppercase tracking-widest text-primary opacity-60">
                  {situation.replace(/_/g, " ")}
                </p>
                <p className="text-sm leading-relaxed">{script}</p>
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
  muted?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border p-4 text-center transition-all",
        highlighted
          ? "border-primary bg-primary/5 shadow-lg shadow-primary/5"
          : "border-canvas bg-secondary/30"
      )}
    >
      <p className="text-[9px] font-mono font-bold uppercase tracking-[0.2em] text-muted-foreground mb-1">
        {label}
      </p>
      <p className={cn(
        "text-2xl font-bold tabular-nums tracking-tight",
        highlighted ? "text-primary" : "text-foreground"
      )}>{value}</p>
    </div>
  );
}
