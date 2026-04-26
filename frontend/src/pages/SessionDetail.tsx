import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { ApiError, getSession } from "@/lib/api";
import CostBreakdown from "@/components/CostBreakdown";
import FileList from "@/components/FileList";
import OfferAnalyser from "@/components/OfferAnalyser";
import PackPicker from "@/components/PackPicker";
import SessionHeader from "@/components/SessionHeader";
import VerdictEvidence from "@/components/VerdictEvidence";
import VerdictHeadline from "@/components/VerdictHeadline";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

interface VerdictPayload {
  decision?: "GO" | "NO_GO";
  headline?: string;
  confidence_pct?: number;
  reasoning?: Array<{
    claim?: string;
    supporting_evidence?: string;
    citation?: import("@/lib/types").Citation;
  }>;
  hard_blockers?: Array<{
    type?: string;
    detail?: string;
    citation?: import("@/lib/types").Citation;
  }>;
  stretch_concerns?: Array<{
    type?: string;
    detail?: string;
    citation?: import("@/lib/types").Citation;
  }>;
}

interface BundlePayload {
  extracted_jd?: { role_title?: string };
  company_research?: { company_name?: string };
  // Other fields read by VerdictEvidence — see its BundleData typing.
}

export default function SessionDetail() {
  const { id = "" } = useParams();
  const session = useQuery({
    queryKey: ["session", id],
    queryFn: () => getSession(id),
    enabled: Boolean(id),
    retry: false,
    // Poll while the verdict hasn't landed yet — the runner finishes
    // detached if the user navigated away from the dashboard. Once
    // verdict is present we stop polling to avoid idle network noise.
    refetchInterval: (query) => {
      const data = query.state.data;
      // Cast: SessionDetailResponse may have verdict in different shape;
      // the absence of any verdict object means we're still waiting.
      const v = (data as { verdict?: unknown } | undefined)?.verdict;
      return v ? false : 4000;
    },
    refetchIntervalInBackground: false,
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
  const role = bundle?.extracted_jd?.role_title ?? null;
  const company = bundle?.company_research?.company_name ?? null;

  return (
    <div className="space-y-6">
      <SessionHeader
        title="Session"
        decision={verdict?.decision ?? null}
        confidencePct={verdict?.confidence_pct ?? null}
        role={role}
        company={company}
        jobUrl={s.job_url}
      />

      {/* Verdict + reasoning + citations as clickable source links. */}
      <VerdictHeadline verdict={verdict} />

      {/* Hub — 4 pack cards. Each card's "View / edit" navigates to
          /sessions/:id/{pack} which renders the deep view. */}
      <PackPicker
        sessionId={s.id}
        roleTitle={role}
        files={s.generated_files}
      />

      {bundle && <OfferAnalyser sessionId={s.id} />}

      <FileList files={s.generated_files} />

      <CostBreakdown summary={s.cost_summary} />

      {/* Full evidence — collapsed by default, available for audit. */}
      <VerdictEvidence bundle={bundle} verdict={verdict} />
    </div>
  );
}
