import { Link } from "react-router-dom";
import { ArrowLeft, ExternalLink, Hash, Layout } from "lucide-react";
import { cn } from "@/lib/utils";
import type { VerdictLabel } from "@/lib/types";
import { isPositiveVerdict, isBlockingVerdict, formatVerdictLabel } from "@/lib/verdict";

interface Props {
  title: string;
  decision?: VerdictLabel | null;
  confidencePct?: number | null;
  role?: string | null;
  company?: string | null;
  jobUrl?: string | null;
  sessionId?: string;
  /** When set, render a "← Back to {label}" link to the given path. */
  backTo?: { label: string; href: string } | null;
}

export default function SessionHeader({
  title,
  decision,
  confidencePct,
  role,
  company,
  jobUrl,
  sessionId,
  backTo,
}: Props) {
  const isPositive = decision ? isPositiveVerdict(decision) : false;
  const isBlocked = decision ? isBlockingVerdict(decision) : false;
  const displayLabel = decision ? formatVerdictLabel(decision) : null;
  return (
    <header className="flex flex-col gap-6 relative">
      <div className="absolute -top-12 -left-12 w-64 h-64 bg-primary/5 rounded-full blur-3xl pointer-events-none" />
      
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 relative z-10">
        <div className="space-y-4">
          <div className="flex items-center gap-4">
            {backTo ? (
              <Link
                to={backTo.href}
                className="group inline-flex items-center gap-2 px-3 py-1 rounded-full bg-secondary/50 border border-canvas text-[10px] font-bold uppercase tracking-widest text-muted-foreground hover:text-primary hover:border-primary/30 transition-all shadow-sm"
              >
                <ArrowLeft className="h-3 w-3 transition-transform group-hover:-translate-x-1" aria-hidden />
                {backTo.label}
              </Link>
            ) : (
              <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-primary/10 border border-primary/20 text-[10px] font-bold uppercase tracking-[0.2em] text-primary shadow-sm">
                <Layout className="h-3 w-3" />
                Session Analysis
              </div>
            )}
            
            {sessionId && (
              <div className="flex items-center gap-1.5 text-[10px] font-mono text-muted-foreground opacity-50 uppercase tracking-tighter">
                <Hash className="h-3 w-3" />
                Ref: {sessionId.slice(0, 8)}
              </div>
            )}
          </div>

          <div className="space-y-1">
            <h1 className="text-5xl font-serif tracking-tight leading-none text-foreground drop-shadow-sm">
              {role ?? title}
            </h1>
            {company && (
              <div className="flex items-center gap-3">
                <div className="h-px w-8 bg-primary/30" />
                <p className="text-xl font-mono text-muted-foreground tracking-tight">
                  <span className="opacity-40">@</span> {company}
                </p>
              </div>
            )}
          </div>
        </div>

        {decision && (
          <div className="flex items-center gap-6 p-4 rounded-3xl bg-secondary/30 border border-canvas backdrop-blur-md shadow-xl">
             <div className="text-right space-y-0.5">
               <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground">Recommendation</p>
               <p className={cn("text-2xl font-serif font-black tracking-tighter", isPositive ? "text-success" : isBlocked ? "text-destructive" : "text-muted-foreground")}>
                 {displayLabel}
               </p>
             </div>
             
             <div className="h-10 w-px bg-canvas" />
             
             <div className="space-y-1">
                <div className="flex items-center gap-2">
                   <div className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
                   <span className="text-[10px] font-mono font-bold uppercase tracking-widest text-muted-foreground">Confidence</span>
                </div>
                <div className="flex items-end gap-1">
                   <span className="text-2xl font-mono font-bold tracking-tighter tabular-nums leading-none">{confidencePct ?? '??'}</span>
                   <span className="text-[10px] font-mono opacity-50 mb-0.5">%</span>
                </div>
             </div>
          </div>
        )}
      </div>

      {jobUrl && (
        <div className="flex items-center gap-3 p-1.5 pl-3 rounded-full bg-background/50 border border-canvas group w-fit shadow-sm backdrop-blur-sm hover:border-primary/30 transition-colors">
          <span className="text-[9px] font-bold font-mono text-primary uppercase tracking-[0.2em]">Job Source</span>
          <div className="h-4 w-px bg-canvas" />
          <a
            href={jobUrl}
            target="_blank"
            rel="noreferrer"
            className="text-[11px] font-mono truncate max-w-[200px] sm:max-w-sm text-muted-foreground hover:text-primary transition-colors flex items-center gap-2"
          >
            {jobUrl}
            <ExternalLink className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity" />
          </a>
        </div>
      )}
    </header>
  );
}
