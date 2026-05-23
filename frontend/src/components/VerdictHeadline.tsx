import { motion } from "motion/react";
import { AlertTriangle, CheckCircle2, Fingerprint, ShieldAlert, Scale } from "lucide-react";

import type { VerdictPayload, VerdictReasoningPoint } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import CitationLink from "@/components/CitationLink";
import { cn } from "@/lib/utils";
import { getVerdictTone, formatVerdictLabel, isBlockingVerdict } from "@/lib/verdict";

interface Props {
  verdict: VerdictPayload | null;
}

const cardVariants = {
  initial: { opacity: 0, scale: 0.98 },
  animate: {
    opacity: 1,
    scale: 1,
    transition: {
      duration: 0.4,
      delayChildren: 0.15,
      staggerChildren: 0.08,
    },
  },
} as const;

const pieceVariants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.35 } },
} as const;

export default function VerdictHeadline({ verdict }: Props) {
  if (!verdict?.decision) return null;

  const label = verdict.decision;
  const tone = getVerdictTone(label);
  const isBlocked = isBlockingVerdict(label);

  return (
    <motion.div
      variants={cardVariants}
      initial="initial"
      animate="animate"
      key={verdict.decision}
      className="relative"
    >
      <Card
        className={cn(
          "border-2 overflow-hidden relative group",
          isBlocked ? "border-destructive/40 shadow-[0_0_20px_rgba(220,38,38,0.05)]" : "border-success/40 shadow-[0_0_20px_rgba(34,197,94,0.05)]",
        )}
      >
        <div className={cn(
          "absolute top-0 left-0 w-full h-1 bg-gradient-to-r",
          isBlocked ? "from-destructive/40 via-destructive/60 to-destructive/40" : "from-success/40 via-success/60 to-success/40"
        )} />
        
        <div className="absolute inset-0 bg-grid-white/[0.02] bg-[size:20px_20px] pointer-events-none" />
        
        <CardHeader className="space-y-4 relative z-10 border-b border-canvas bg-secondary/10">
          <motion.div
            variants={pieceVariants}
            className="flex flex-wrap items-center justify-between gap-2"
          >
            <div className="flex items-center gap-2">
              <Badge variant={tone === "destructive" ? "destructive" : tone === "warning" ? "secondary" : tone === "success" ? "success" : "secondary"} className="font-mono tracking-tighter uppercase px-3">
                {isBlocked ? (
                  <ShieldAlert className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                ) : (
                  <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                )}
                {formatVerdictLabel(label)}
              </Badge>
              {verdict.confidence_pct !== undefined && (
                <div className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-canvas bg-background/50">
                  <Fingerprint className="h-3 w-3 text-primary" />
                  <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest font-bold">
                    {verdict.confidence_pct}% Confidence
                  </span>
                </div>
              )}
            </div>
            <span className="text-[9px] font-mono text-muted-foreground uppercase tracking-[0.3em] opacity-80">Opus-4.7-Forensic-Engine</span>
          </motion.div>
          {verdict.headline && (
            <motion.h2
              variants={pieceVariants}
              className="text-2xl font-serif font-bold tracking-tight leading-tight"
            >
              {verdict.headline}
            </motion.h2>
          )}
        </CardHeader>
        <CardContent className="space-y-6 pt-6 relative z-10">
          {verdict.hard_blockers && verdict.hard_blockers.length > 0 && (
            <motion.div variants={pieceVariants}>
              <ReasonGroup
                title="Critical Obstructions"
                icon={ShieldAlert}
                tone="destructive"
                items={verdict.hard_blockers.map((b) => ({
                  claim: b.type,
                  supporting_evidence: b.detail,
                  citation: b.citation,
                }))}
              />
            </motion.div>
          )}

          {verdict.reasoning && verdict.reasoning.length > 0 && (
            <motion.div variants={pieceVariants}>
              <ReasonGroup
                title="Reasoning"
                icon={Scale}
                tone="default"
                items={verdict.reasoning}
              />
            </motion.div>
          )}

          {verdict.stretch_concerns && verdict.stretch_concerns.length > 0 && (
            <motion.div variants={pieceVariants}>
              <ReasonGroup
                title="Residual Risks"
                icon={AlertTriangle}
                tone="warning"
                items={verdict.stretch_concerns.map((c) => ({
                  claim: c.type,
                  supporting_evidence: c.detail,
                  citation: c.citation,
                }))}
              />
            </motion.div>
          )}
        </CardContent>
        
        {/* Scan line effect */}
        <div className="absolute inset-0 pointer-events-none overflow-hidden opacity-20">
          <div className="w-full h-[100px] bg-gradient-to-b from-transparent via-primary/5 to-transparent absolute -top-[100px] left-0 animate-scan" />
        </div>
      </Card>
    </motion.div>
  );
}

function ReasonGroup({
  title,
  icon: Icon,
  tone,
  items,
}: {
  title: string;
  icon: any;
  tone: "default" | "destructive" | "warning";
  items: VerdictReasoningPoint[];
}) {
  const titleClass = cn(
    "flex items-center gap-2 text-[10px] font-mono font-bold uppercase tracking-[0.2em] mb-3",
    tone === "destructive" && "text-destructive",
    tone === "warning" && "text-warning",
    tone === "default" && "text-primary",
  );

  return (
    <section>
      <p className={titleClass}>
        {Icon && <Icon className="h-3.5 w-3.5" aria-hidden />}
        {title}
      </p>
      <div className="grid gap-3">
        {items.map((r, i) => (
          <div
            key={i}
            className={cn(
              "rounded-xl border p-4 transition-all relative group/item",
              tone === "destructive" && "border-destructive/30 bg-destructive/5 shadow-[inset_0_0_15px_rgba(220,38,38,0.03)]",
              tone === "warning" && "border-warning/30 bg-warning/5 shadow-[inset_0_0_15px_rgba(var(--warning),0.03)]",
              tone === "default" && "border-canvas bg-secondary/5 hover:bg-secondary/10",
            )}
          >
            <div className={cn(
              "absolute left-0 top-0 bottom-0 w-1 transition-colors",
              tone === "destructive" && "bg-destructive/20 group-hover/item:bg-destructive/50",
              tone === "warning" && "bg-warning/20 group-hover/item:bg-warning/50",
              tone === "default" && "bg-primary/10 group-hover/item:bg-primary/30",
            )} />
            
            {r.claim && <p className="font-bold text-foreground leading-snug tracking-tight mb-1">{r.claim}</p>}
            {r.supporting_evidence && (
              <p className="text-xs text-muted-foreground leading-relaxed italic">
                {r.supporting_evidence}
              </p>
            )}
            {r.citation && (
              <div className="mt-3 flex justify-end">
                <CitationLink citation={r.citation} variant="inline" />
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
