import { motion } from "motion/react";
import { ArrowRight, ShieldCheck, ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import Gauge from "@/components/ui/Gauge";
import { cn } from "@/lib/utils";

// Loose typing for the verdict payload — research_bundle/verdict
// pass through as raw dicts in the API contract; the dashboard reads
// only the fields it renders.
interface VerdictData {
  decision?: "GO" | "NO_GO";
  headline?: string;
  confidence_pct?: number;
  hard_blockers?: Array<{ type?: string; detail?: string }>;
  stretch_concerns?: Array<{ type?: string; detail?: string }>;
}

interface BundleData {
  extracted_jd?: { role_title?: string };
  company_research?: { company_name?: string };
}

interface Props {
  verdict: VerdictData;
  bundle?: BundleData | null;
  sessionId?: string;
}

export default function VerdictCard({ verdict, bundle, sessionId }: Props) {
  const decision = verdict.decision ?? "NO_GO";
  const isGo = decision === "GO";
  const role = bundle?.extracted_jd?.role_title;
  const company = bundle?.company_research?.company_name;
  const blockers = verdict.hard_blockers ?? [];
  const concerns = verdict.stretch_concerns ?? [];

  return (
    <Card className={cn(
      "relative overflow-hidden border-2 transition-all duration-500",
      isGo ? "border-success/30 shadow-2xl shadow-success/10" : "border-destructive/30 shadow-2xl shadow-destructive/10"
    )}>
      {/* Dramatic Stamp Overlay */}
      <motion.div
        initial={{ scale: 2, opacity: 0, rotate: -20 }}
        animate={{ scale: 1, opacity: 0.15, rotate: -15 }}
        className={cn(
          "absolute -right-8 -top-8 text-[8rem] font-black uppercase pointer-events-none select-none",
          isGo ? "text-success" : "text-destructive"
        )}
      >
        {decision}
      </motion.div>

      <CardHeader className="relative z-10">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              {isGo ? (
                <ShieldCheck className="h-8 w-8 text-success" />
              ) : (
                <ShieldAlert className="h-8 w-8 text-destructive" />
              )}
              <div className="space-y-0.5">
                <Badge variant={isGo ? "success" : "destructive"} className="uppercase tracking-widest text-[10px] px-2 py-0">
                  {isGo ? "Approved Case" : "Risk Detected"}
                </Badge>
                <h3 className="font-serif text-2xl tracking-tight">
                  {isGo ? "Go for it." : "Picky says no."}
                </h3>
              </div>
            </div>

            <div className="space-y-1">
              {(role || company) && (
                <p className="text-sm font-bold font-mono">
                  {role?.toUpperCase()}
                  {role && company && (
                    <span className="text-muted-foreground opacity-50"> @ {company?.toUpperCase()}</span>
                  )}
                </p>
              )}
              {verdict.headline && (
                <p className="text-sm text-muted-foreground leading-relaxed italic max-w-md">
                  "{verdict.headline}"
                </p>
              )}
            </div>
          </div>
          
          <div className="flex flex-col items-end gap-4">
             {verdict.confidence_pct !== undefined && (
                <Gauge
                  value={Math.max(0, Math.min(1, verdict.confidence_pct / 100))}
                  label="Confidence"
                  sublabel={`${verdict.confidence_pct}%`}
                  color={isGo ? "success" : "destructive"}
                />
              )}
            {sessionId && (
              <Link
                to={`/sessions/${sessionId}`}
                className={cn(
                  buttonVariants({ variant: isGo ? "success" : "destructive", size: "sm" }),
                  "font-bold uppercase tracking-widest text-[10px]"
                )}
              >
                Inspect Evidence
                <ArrowRight className="ml-2 h-3 w-3" />
              </Link>
            )}
          </div>
        </div>
      </CardHeader>

      {(blockers.length > 0 || concerns.length > 0) && (
        <CardContent className="relative z-10 space-y-4 pt-0">
          <div className="h-px bg-canvas w-full" />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {blockers.length > 0 && (
              <div className="space-y-2">
                <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-destructive">
                  Critical Blockers
                </p>
                <ul className="space-y-2">
                  {blockers.map((b, i) => (
                    <li key={i} className="text-xs bg-destructive/5 border border-destructive/10 p-2 rounded-lg flex gap-2">
                      <span className="text-destructive font-bold">!</span>
                      <span>
                        <span className="font-bold">{b.type}:</span> {b.detail}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {concerns.length > 0 && (
              <div className="space-y-2">
                <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
                  Stretch Concerns
                </p>
                <ul className="space-y-2">
                  {concerns.map((c, i) => (
                    <li key={i} className="text-xs bg-muted/5 border border-canvas p-2 rounded-lg flex gap-2">
                      <span className="text-muted-foreground">?</span>
                      <span>
                        <span className="font-bold">{c.type}:</span> {c.detail}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </CardContent>
      )}
    </Card>
  );
}
