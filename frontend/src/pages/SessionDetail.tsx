import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { ApiError, getSession } from "@/lib/api";
import VerdictEvidence from "@/components/VerdictEvidence";
import PackGenerator from "@/components/PackGenerator";
import FileList from "@/components/FileList";
import CostBreakdown from "@/components/CostBreakdown";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

interface VerdictPayload {
  decision?: "GO" | "NO_GO";
  headline?: string;
  confidence_pct?: number;
  reasoning?: Array<{ claim?: string; supporting_evidence?: string }>;
  hard_blockers?: Array<{ type?: string; detail?: string }>;
  stretch_concerns?: Array<{ type?: string; detail?: string }>;
}

interface BundlePayload {
  extracted_jd?: { role_title?: string };
  company_research?: { company_name?: string };
  // Other fields (companies_house, sponsor_status, soc_check, ghost_job,
  // red_flags, salary_signals) are read by VerdictEvidence — see its
  // BundleData typing.
}

export default function SessionDetail() {
  const { id = "" } = useParams();
  const session = useQuery({
    queryKey: ["session", id],
    queryFn: () => getSession(id),
    enabled: Boolean(id),
    retry: false,
  });

  if (session.isPending) {
    return <Skeleton className="h-64 w-full" />;
  }

  if (session.isError || !session.data) {
    const err = session.error as ApiError | undefined;
    const notFound = err?.code === "session_not_found";
    return (
      <Card>
        <CardHeader>
          <CardTitle>
            {notFound ? "Session not found" : "Failed to load session"}
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {notFound
            ? "The session either doesn't exist or isn't yours."
            : (err?.message ?? "Unknown error.")}
          <p className="mt-2">
            <Link to="/" className="underline">
              Back to dashboard
            </Link>
          </p>
        </CardContent>
      </Card>
    );
  }

  const s = session.data;
  const verdict = s.verdict as VerdictPayload | null;
  const bundle = s.research_bundle as BundlePayload | null;
  const role = bundle?.extracted_jd?.role_title;
  const company = bundle?.company_research?.company_name;
  const decision = verdict?.decision;

  return (
    <div className="space-y-6">
      {/* Header */}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              {decision && (
                <Badge
                  variant={decision === "GO" ? "success" : "destructive"}
                >
                  {decision}
                  {verdict?.confidence_pct !== undefined && (
                    <span className="ml-1 opacity-70">
                      · {verdict.confidence_pct}%
                    </span>
                  )}
                </Badge>
              )}
              <CardTitle className="text-base">
                {role ?? s.job_url ?? s.id}
                {company && (
                  <span className="text-muted-foreground"> · {company}</span>
                )}
              </CardTitle>
              {verdict?.headline && (
                <p className="text-sm text-muted-foreground">
                  {verdict.headline}
                </p>
              )}
              {s.job_url && (
                <p className="text-xs text-muted-foreground">
                  <a
                    href={s.job_url}
                    target="_blank"
                    rel="noreferrer"
                    className="hover:underline"
                  >
                    {s.job_url}
                  </a>
                </p>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs uppercase text-muted-foreground">
                Intent
              </dt>
              <dd>{s.intent}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-muted-foreground">
                Created
              </dt>
              <dd>{new Date(s.created_at).toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-muted-foreground">
                Files
              </dt>
              <dd>{s.generated_files.length}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-muted-foreground">
                Spend so far
              </dt>
              <dd className="tabular-nums">
                ${s.cost_summary.total_usd.toFixed(4)}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      {/* Per-source evidence */}
      <VerdictEvidence bundle={bundle} verdict={verdict} />

      {/* Pack generation — only meaningful once a verdict exists */}
      {bundle && <PackGenerator sessionId={s.id} />}

      {/* Files panel */}
      <FileList files={s.generated_files} />

      {/* Cost breakdown */}
      <CostBreakdown summary={s.cost_summary} />
    </div>
  );
}
