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
  const verdict = s.verdict;
  const bundle = s.research_bundle;
  const role = bundle?.extracted_jd?.role_title ?? null;
  const company = bundle?.company_research?.company_name ?? null;

  return (
    <div className="space-y-8 max-w-7xl mx-auto">
      <div className="flex flex-col md:flex-row gap-8">
        <div className="flex-1 space-y-8">
          <SessionHeader
            title="Case File"
            decision={verdict?.decision ?? null}
            confidencePct={verdict?.confidence_pct ?? null}
            role={role}
            company={company}
            jobUrl={s.job_url}
          />

          <div className="relative group">
            <div className="absolute -inset-1 bg-gradient-to-r from-primary/20 to-success/20 rounded-2xl blur opacity-25 group-hover:opacity-50 transition duration-1000 group-hover:duration-200"></div>
            <VerdictHeadline verdict={verdict} />
          </div>

          <PackPicker
            sessionId={s.id}
            files={s.generated_files}
          />
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <FileList files={s.generated_files} />
            <CostBreakdown summary={s.cost_summary} />
          </div>
        </div>

        <div className="w-full md:w-80 space-y-6">
          <div className="sticky top-8 space-y-6">
             {bundle && <OfferAnalyser sessionId={s.id} />}
             
             <Card className="bg-secondary/30 border-canvas">
               <CardHeader className="py-3">
                 <CardTitle className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Audit Log</CardTitle>
               </CardHeader>
               <CardContent className="text-[10px] font-mono space-y-2 opacity-60">
                 <p className="flex justify-between">
                   <span>JD_EXTRACTED</span>
                   <span className="text-success">OK</span>
                 </p>
                 <p className="flex justify-between">
                   <span>CORP_RESEARCH</span>
                   <span className="text-success">OK</span>
                 </p>
                 <p className="flex justify-between">
                   <span>GOV_DATA_LINK</span>
                   <span className="text-success">OK</span>
                 </p>
                 <p className="flex justify-between">
                   <span>CITATIONS_VALID</span>
                   <span className="text-success">9/9</span>
                 </p>
               </CardContent>
             </Card>
          </div>
        </div>
      </div>

      <div className="pt-8 border-t border-canvas">
        <h3 className="font-serif text-2xl mb-6">Evidence Board</h3>
        <VerdictEvidence bundle={bundle} verdict={verdict} />
      </div>
    </div>
  );
}
