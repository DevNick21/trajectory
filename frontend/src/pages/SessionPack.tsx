import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, getSession } from "@/lib/api";
import DeepWork from "@/components/DeepWork";
import DeepWorkCoverLetter from "@/components/DeepWorkCoverLetter";
import DeepWorkQuestions from "@/components/DeepWorkQuestions";
import DeepWorkSalary from "@/components/DeepWorkSalary";
import SessionHeader from "@/components/SessionHeader";
import type {
  CVOutput,
  CoverLetterOutput,
  LikelyQuestionsOutput,
  PackGeneratorName,
  SalaryRecommendation,
} from "@/lib/types";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

interface VerdictPayload {
  decision?: "GO" | "NO_GO";
  confidence_pct?: number;
}

interface BundlePayload {
  extracted_jd?: {
    role_title?: string;
    location?: string;
    remote_policy?: string;
    seniority_signal?: string;
    salary_band?: { min_gbp?: number; max_gbp?: number; period?: string } | null;
    required_skills?: string[];
  };
  company_research?: {
    company_name?: string;
    company_domain?: string | null;
  };
}

const ROUTE_TO_GENERATOR: Record<string, PackGeneratorName> = {
  cv: "cv",
  "cover-letter": "cover_letter",
  salary: "salary",
  questions: "questions",
};

const PACK_TITLE: Record<PackGeneratorName, string> = {
  cv: "Tailored CV",
  cover_letter: "Custom cover letter",
  salary: "Salary negotiation strategy",
  questions: "Interview prep",
};

export default function SessionPack() {
  const { id = "", pack: packParam = "" } = useParams();
  const queryClient = useQueryClient();
  const generator = ROUTE_TO_GENERATOR[packParam];

  const session = useQuery({
    queryKey: ["session", id],
    queryFn: () => getSession(id),
    enabled: Boolean(id),
    retry: false,
  });

  if (!generator) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Unknown pack</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          <p>
            &ldquo;{packParam}&rdquo; isn&rsquo;t a pack we know about. Try{" "}
            <Link to={`/sessions/${id}`} className="underline">
              the session hub
            </Link>
            .
          </p>
        </CardContent>
      </Card>
    );
  }

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

  // Hydrate the deep view from the SPA's per-session pack cache (set
  // by PackPicker / DeepWork* containers after a successful generate).
  // Cold reload won't have this — the user clicks Generate inside.
  const cached = queryClient.getQueryData(["pack", s.id, generator]);

  return (
    <div className="space-y-6">
      <SessionHeader
        title={PACK_TITLE[generator]}
        decision={verdict?.decision ?? null}
        confidencePct={verdict?.confidence_pct ?? null}
        role={role}
        company={company}
        jobUrl={s.job_url}
        backTo={{ label: "session", href: `/sessions/${s.id}` }}
      />

      {generator === "cv" && (
        <DeepWork
          sessionId={s.id}
          bundle={bundle}
          initialCV={(cached as CVOutput | undefined) ?? null}
        />
      )}
      {generator === "cover_letter" && (
        <DeepWorkCoverLetter
          sessionId={s.id}
          bundle={bundle}
          initialOutput={(cached as CoverLetterOutput | undefined) ?? null}
        />
      )}
      {generator === "salary" && (
        <DeepWorkSalary
          sessionId={s.id}
          bundle={bundle}
          initialOutput={(cached as SalaryRecommendation | undefined) ?? null}
        />
      )}
      {generator === "questions" && (
        <DeepWorkQuestions
          sessionId={s.id}
          bundle={bundle}
          initialOutput={(cached as LikelyQuestionsOutput | undefined) ?? null}
        />
      )}
    </div>
  );
}
