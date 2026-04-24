import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

// Loose typing for the verdict payload — research_bundle/verdict
// pass through as raw dicts in the API contract; the dashboard reads
// only the fields it renders. Tightening these lives in the codegen
// follow-up.
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
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <Badge variant={isGo ? "success" : "destructive"}>
              {decision}
              {verdict.confidence_pct !== undefined && (
                <span className="ml-1 opacity-70">
                  · {verdict.confidence_pct}%
                </span>
              )}
            </Badge>
            {(role || company) && (
              <p className="text-sm font-medium">
                {role}
                {role && company && (
                  <span className="text-muted-foreground"> · {company}</span>
                )}
                {!role && company}
              </p>
            )}
            {verdict.headline && (
              <p className="text-sm text-muted-foreground">
                {verdict.headline}
              </p>
            )}
          </div>
          {sessionId && (
            <Link
              to={`/sessions/${sessionId}`}
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              Detail
              <ArrowRight className="ml-1 h-4 w-4" />
            </Link>
          )}
        </div>
      </CardHeader>
      {(blockers.length > 0 || concerns.length > 0) && (
        <CardContent className="space-y-3">
          {blockers.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-destructive">
                Hard blockers
              </p>
              <ul className="mt-1 list-disc pl-5 text-sm">
                {blockers.map((b, i) => (
                  <li key={i}>
                    <span className="font-medium">{b.type}</span>
                    {b.detail && <span className="text-muted-foreground"> · {b.detail}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {concerns.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Stretch concerns
              </p>
              <ul className="mt-1 list-disc pl-5 text-sm">
                {concerns.map((c, i) => (
                  <li key={i}>
                    <span className="font-medium">{c.type}</span>
                    {c.detail && <span className="text-muted-foreground"> · {c.detail}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
