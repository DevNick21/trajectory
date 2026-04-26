import { AlertOctagon, AlertTriangle, CheckCircle2, XCircle } from "lucide-react";

import type { Citation } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import CitationLink from "@/components/CitationLink";
import { cn } from "@/lib/utils";

interface ReasoningPoint {
  claim?: string;
  supporting_evidence?: string;
  citation?: Citation;
}

interface HardBlocker {
  type?: string;
  detail?: string;
  citation?: Citation;
}

interface StretchConcern {
  type?: string;
  detail?: string;
  citation?: Citation;
}

interface VerdictView {
  decision?: "GO" | "NO_GO";
  headline?: string;
  confidence_pct?: number;
  reasoning?: ReasoningPoint[];
  hard_blockers?: HardBlocker[];
  stretch_concerns?: StretchConcern[];
}

interface Props {
  verdict: VerdictView | null;
}

/** Top-of-hub verdict block. Decision + headline + reasoning, with
 *  citations rendered as clickable source links. NO_GO gets a muted
 *  red/orange border to match the mockup. */
export default function VerdictHeadline({ verdict }: Props) {
  if (!verdict?.decision) return null;

  const isNoGo = verdict.decision === "NO_GO";

  return (
    <Card
      className={cn(
        "border-2",
        isNoGo ? "border-destructive/40" : "border-success/40",
      )}
    >
      <CardHeader className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={isNoGo ? "destructive" : "success"}>
            {isNoGo ? (
              <XCircle className="mr-1 h-3.5 w-3.5" aria-hidden />
            ) : (
              <CheckCircle2 className="mr-1 h-3.5 w-3.5" aria-hidden />
            )}
            Opus 4.7 Verdict · {verdict.decision}
          </Badge>
          {verdict.confidence_pct !== undefined && (
            <span className="text-xs text-muted-foreground">
              {verdict.confidence_pct}% confidence
            </span>
          )}
        </div>
        {verdict.headline && (
          <p className="text-lg font-semibold leading-snug">
            {verdict.headline}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {verdict.hard_blockers && verdict.hard_blockers.length > 0 && (
          <ReasonGroup
            title="Hard blockers"
            icon={AlertOctagon}
            tone="destructive"
            items={verdict.hard_blockers.map((b) => ({
              claim: b.type,
              supporting_evidence: b.detail,
              citation: b.citation,
            }))}
          />
        )}

        {verdict.reasoning && verdict.reasoning.length > 0 && (
          <ReasonGroup
            title="Reasoning"
            icon={null}
            tone="default"
            items={verdict.reasoning}
          />
        )}

        {verdict.stretch_concerns && verdict.stretch_concerns.length > 0 && (
          <ReasonGroup
            title="Stretch concerns"
            icon={AlertTriangle}
            tone="warning"
            items={verdict.stretch_concerns.map((c) => ({
              claim: c.type,
              supporting_evidence: c.detail,
              citation: c.citation,
            }))}
          />
        )}
      </CardContent>
    </Card>
  );
}

function ReasonGroup({
  title,
  icon: Icon,
  tone,
  items,
}: {
  title: string;
  icon: typeof AlertOctagon | null;
  tone: "default" | "destructive" | "warning";
  items: ReasoningPoint[];
}) {
  const titleClass = cn(
    "flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide",
    tone === "destructive" && "text-destructive",
    tone === "warning" && "text-amber-600",
    tone === "default" && "text-muted-foreground",
  );

  return (
    <section>
      <p className={titleClass}>
        {Icon && <Icon className="h-3.5 w-3.5" aria-hidden />}
        {title}
      </p>
      <ul className="mt-2 space-y-2">
        {items.map((r, i) => (
          <li
            key={i}
            className={cn(
              "rounded-md border p-3 text-sm",
              tone === "destructive" && "border-destructive/30 bg-destructive/5",
              tone === "warning" && "border-amber-500/30 bg-amber-50/40",
            )}
          >
            {r.claim && <p className="font-medium">{r.claim}</p>}
            {r.supporting_evidence && (
              <p className="mt-1 text-muted-foreground">
                {r.supporting_evidence}
              </p>
            )}
            {r.citation && (
              <div className="mt-2">
                <CitationLink citation={r.citation} variant="inline" />
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
