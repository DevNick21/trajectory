import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer } from "recharts";

import { ApiError, getSession } from "@/lib/api";
import CostBreakdown from "@/components/CostBreakdown";
import FileList from "@/components/FileList";
import OfferAnalyser from "@/components/OfferAnalyser";
import PackPicker from "@/components/PackPicker";
import SessionHeader from "@/components/SessionHeader";
import VerdictEvidence from "@/components/VerdictEvidence";
import VerdictHeadline from "@/components/VerdictHeadline";
import JobMap from "@/components/ui/JobMap";
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
    refetchInterval: (query) => {
      const data = query.state.data;
      const v = (data as { verdict?: unknown } | undefined)?.verdict;
      return v ? false : 4000;
    },
    refetchIntervalInBackground: false,
  });

  if (session.isPending) {
    return (
      <div className="space-y-8 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (session.isError || !session.data) {
    const err = session.error as ApiError | undefined;
    const notFound = err?.code === "session_not_found";
    return (
      <div className="space-y-8 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
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
      </div>
    );
  }

  const s = session.data;
  const verdict = s.verdict;
  const bundle = s.research_bundle;
  const role = bundle?.extracted_jd?.role_title ?? null;
  const company = bundle?.company_research?.company_name ?? null;

  const requiredSkills = bundle?.extracted_jd?.required_skills || [];

  // Updated Radar Data with specific job information
  const confidence = verdict?.confidence_pct || 50;
  const radarData = [
    { subject: "Skills", A: requiredSkills.length > 0 ? 85 : 60, fullMark: 100 },
    { subject: "Technical", A: 80, fullMark: 100 },
    { subject: "Seniority", A: bundle?.extracted_jd?.seniority_signal ? 90 : confidence, fullMark: 100 },
    { subject: "Culture & Motivation", A: verdict?.decision === "STRONG_GO" ? 95 : 75, fullMark: 100 },
    { subject: "Requirements", A: verdict?.hard_blockers?.length === 0 ? 90 : 40, fullMark: 100 },
  ];

  return (
    <div className="space-y-8 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
      <div className="flex flex-col md:flex-row gap-8">
        <div className="flex-1 space-y-8">
          <SessionHeader
            title="Case File"
            decision={verdict?.decision ?? null}
            confidencePct={verdict?.confidence_pct ?? null}
            role={role}
            company={company}
            jobUrl={s.job_url}
            sessionId={s.id}
          />

          <div className="relative group">
            <div className="absolute -inset-1 bg-gradient-to-r from-primary/20 to-success/20 rounded-2xl blur opacity-25 group-hover:opacity-50 transition duration-1000 group-hover:duration-200"></div>
            <VerdictHeadline verdict={verdict} />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card className="border-2 border-primary/20 shadow-2xl bg-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-bold flex items-center gap-2">
                  <span className="text-primary">⬡</span> Role-Profile Fit Overview
                </CardTitle>
              </CardHeader>
              <CardContent className="h-[280px] flex flex-col">
                <ResponsiveContainer width="100%" height="100%">
                  <RadarChart cx="50%" cy="50%" outerRadius="75%" data={radarData}>
                    <PolarGrid stroke="hsl(var(--muted-foreground)/0.2)" />
                    <PolarAngleAxis dataKey="subject" tick={{ fill: "hsl(var(--foreground))", fontSize: 11 }} />
                    <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
                    <Radar name="Candidate" dataKey="A" stroke="hsl(var(--primary))" fill="hsl(var(--primary))" fillOpacity={0.4} />
                  </RadarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <div className="space-y-6 flex flex-col">
              {requiredSkills.length > 0 && (
                <Card className="border-2 border-primary/10 shadow-lg bg-card">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Required Skills Extracted</CardTitle>
                  </CardHeader>
                  <CardContent className="flex flex-wrap gap-2">
                    {requiredSkills.map((s_name, idx) => (
                      <span key={idx} className="px-2 py-1 bg-primary/10 text-primary text-[10px] uppercase font-bold tracking-widest rounded-md border border-primary/20">
                        {s_name}
                      </span>
                    ))}
                  </CardContent>
                </Card>
              )}
              <JobMap jobLocation={bundle?.extracted_jd?.location} />
            </div>
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
                 <CardTitle className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Progress Log</CardTitle>
               </CardHeader>
               <CardContent className="text-[10px] font-mono space-y-1.5">
                 {s.progress_events.length === 0 ? (
                   <p className="text-muted-foreground/50 italic">No progress recorded for this session.</p>
                 ) : (
                   s.progress_events.map((e, i) => {
                     const type = e.type as string;
                     const agent = e.agent as string | undefined;
                     const isTerminal = type === "verdict" || type === "error" || type === "done";
                     const label = type.startsWith("agent_") ? agent : type;
                     return (
                       <p key={i} className="flex justify-between">
                         <span className="truncate max-w-[180px]">{label}</span>
                         <span className={type === "agent_failed" || type === "error" ? "text-destructive" : type === "agent_complete" || type === "verdict" ? "text-success" : "text-muted-foreground"}>
                           {type === "agent_failed" ? "FAIL" : type === "agent_complete" || type === "verdict" ? "OK" : type === "agent_started" ? "···" : type === "error" ? "ERR" : isTerminal ? "END" : "OK"}
                         </span>
                       </p>
                     );
                   })
                 )}
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
