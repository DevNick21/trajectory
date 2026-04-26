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
  return (
    <header className="flex flex-col gap-2">
      {backTo && (
        <Link
          to={backTo.href}
          className="inline-flex items-center gap-1 text-xs text-foreground/60 hover:text-foreground"
        >
          <ArrowLeft className="h-3 w-3" aria-hidden />
          Back to {backTo.label}
        </Link>
      )}
      <div className="flex flex-wrap items-center gap-3">
        {decision && (
          <Badge variant={decision === "GO" ? "success" : "destructive"}>
            {decision}
            {confidencePct !== undefined && confidencePct !== null && (
              <span className="ml-1 opacity-70">· {confidencePct}%</span>
            )}
          </Badge>
        )}
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          {title}
        </h1>
      </div>
      <div className="flex flex-col gap-0.5 text-sm text-foreground/70">
        {(role || company) && (
          <p>
            {role ?? "—"}
            {company && <span className="opacity-70"> · {company}</span>}
          </p>
        )}
        {jobUrl && (
          <a
            href={jobUrl}
            target="_blank"
            rel="noreferrer"
            className="text-xs hover:underline"
          >
            {jobUrl}
          </a>
        )}
      </div>
    </header>
  );
}
