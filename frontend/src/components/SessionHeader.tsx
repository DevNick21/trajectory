import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { Badge } from "@/components/ui/badge";

interface Props {
  title: string;
  decision?: "GO" | "NO_GO" | null;
  confidencePct?: number | null;
  role?: string | null;
  company?: string | null;
  jobUrl?: string | null;
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
  backTo,
}: Props) {
  const isGo = decision === "GO";
  return (
    <header className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <div className="space-y-1">
          {backTo ? (
            <Link
              to={backTo.href}
              className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground hover:text-primary transition-colors"
            >
              <ArrowLeft className="h-3 w-3" aria-hidden />
              {backTo.label}
            </Link>
          ) : (
            <div className="text-[10px] font-bold uppercase tracking-[0.3em] text-primary">
              Analysis Active
            </div>
          )}
          <h1 className="text-4xl font-serif tracking-tight">
            {role ?? title}
          </h1>
          {company && (
            <p className="text-lg font-mono text-muted-foreground">
              @ {company}
            </p>
          )}
        </div>

        {decision && (
          <div className="flex flex-col items-end gap-1">
            <Badge variant={isGo ? "success" : "destructive"} className="text-xs px-3 py-1 uppercase font-black">
              {decision}
            </Badge>
            {confidencePct !== undefined && confidencePct !== null && (
              <span className="text-[10px] font-mono opacity-50 uppercase tracking-tighter">
                {confidencePct}% Confidence
              </span>
            )}
          </div>
        )}
      </div>

      {jobUrl && (
        <div className="flex items-center gap-2 p-2 rounded-lg bg-secondary/30 border border-canvas group w-fit">
          <span className="text-[10px] font-mono opacity-40 uppercase">Source</span>
          <a
            href={jobUrl}
            target="_blank"
            rel="noreferrer"
            className="text-xs font-mono truncate max-w-sm hover:text-primary transition-colors"
          >
            {jobUrl}
          </a>
        </div>
      )}
    </header>
  );
}
