import { useReducer, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError, getProfile, listSessions } from "@/lib/api";
import { streamForwardJob } from "@/lib/sse";
import type { ForwardJobEvent, SessionListResponse } from "@/lib/types";
import ForwardJobForm from "@/components/ForwardJobForm";
import NotificationBanner from "@/components/NotificationBanner";
import Phase1Stream, { type AgentTiming } from "@/components/Phase1Stream";
import VerdictCard from "@/components/VerdictCard";
import SessionList from "@/components/SessionList";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

// ---------------------------------------------------------------------------
// SSE state machine — useReducer over the event stream
// ---------------------------------------------------------------------------

type StreamStatus = "idle" | "running" | "complete" | "error";

interface StreamState {
  status: StreamStatus;
  jobUrl: string | null;
  startedAt: number | null;
  completed: Record<string, AgentTiming>;
  verdict: Record<string, unknown> | null;
  errorMessage: string | null;
}

type Action =
  | { kind: "submit"; jobUrl: string; startedAt: number }
  | { kind: "event"; event: ForwardJobEvent };

const initial: StreamState = {
  status: "idle",
  jobUrl: null,
  startedAt: null,
  completed: {},
  verdict: null,
  errorMessage: null,
};

function reducer(state: StreamState, action: Action): StreamState {
  switch (action.kind) {
    case "submit":
      return {
        status: "running",
        jobUrl: action.jobUrl,
        startedAt: action.startedAt,
        completed: {},
        verdict: null,
        errorMessage: null,
      };
    case "event": {
      const e = action.event;
      switch (e.type) {
        case "agent_complete":
          return {
            ...state,
            completed: {
              ...state.completed,
              [e.agent]: { completedAt: Date.now() },
            },
          };
        case "verdict":
          return { ...state, status: "complete", verdict: e.data };
        case "error":
          return {
            ...state,
            status: "error",
            errorMessage: e.data?.message ?? "Research failed.",
          };
        case "done":
          return state.status === "running"
            ? {
                ...state,
                status: "error",
                errorMessage: "Stream ended without a verdict.",
              }
            : state;
        default:
          return state;
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Dashboard() {
  const profile = useQuery({
    queryKey: ["profile"],
    queryFn: getProfile,
    retry: false,
  });
  const queryClient = useQueryClient();
  const [stream, dispatch] = useReducer(reducer, initial);
  const lastSessionIdRef = useRef<string | null>(null);

  const profileError = profile.error as ApiError | undefined;
  const profileMissing =
    profile.isError && profileError?.code === "profile_not_found";
  const canForward = profile.isSuccess;

  const handleSubmit = async (jobUrl: string) => {
    dispatch({ kind: "submit", jobUrl, startedAt: Date.now() });
    toast.info("Picky's looking", {
      description: "Nine checks in parallel. Citations on every claim.",
    });
    try {
      await streamForwardJob(jobUrl, {
        onEvent: (event) => {
          dispatch({ kind: "event", event });
          if (event.type === "verdict") {
            const decision = (event.data?.decision as string | undefined) ?? "?";
            if (decision === "GO") {
              toast.success("Picky says: apply", {
                description: "Worth your time. Open it to see why.",
              });
            } else if (decision === "NO_GO") {
              toast.warning("Picky says: skip it", {
                description: "Hard blockers found. Open it to see which.",
              });
            }
          }
        },
        onError: (err) => {
          dispatch({
            kind: "event",
            event: { type: "error", data: { message: err.message } },
          });
          toast.error("Research failed", { description: err.message });
        },
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Stream failed.";
      dispatch({
        kind: "event",
        event: { type: "error", data: { message } },
      });
      toast.error("Research failed", { description: message });
    } finally {
      const refreshed = await queryClient.fetchQuery<SessionListResponse>({
        queryKey: ["sessions"],
        queryFn: () => listSessions(),
      });
      lastSessionIdRef.current = refreshed.sessions[0]?.id ?? null;
    }
  };

  return (
    <div className="space-y-6">
      {/* Outcome nudges (cross-surface — same data Telegram + email show) */}
      {canForward && <NotificationBanner />}

      {/* Profile gate */}
      {profile.isPending ? (
        <Skeleton className="h-20 w-full" />
      ) : profileMissing ? (
        <Card className="border-l-4 border-l-primary">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Picky needs your context first</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-card-foreground/80">
            <p>
              Without your career history, deal-breakers, and writing samples,
              every verdict will be generic.{" "}
              <a
                href="/onboarding"
                className="text-primary font-medium underline-offset-2 hover:underline"
              >
                Start onboarding →
              </a>
            </p>
          </CardContent>
        </Card>
      ) : profile.isError ? (
        <Card>
          <CardHeader>
            <CardTitle>Profile failed to load</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-destructive">
            {profileError?.message ?? "Unknown error."}
          </CardContent>
        </Card>
      ) : null}

      {/* Forward job form */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <span className="font-mono text-primary text-sm">›</span>
            Paste a job URL
          </CardTitle>
          <p className="text-xs text-card-foreground/60 mt-1">
            Picky scrapes the company page, runs nine checks against UK gov data,
            and takes a position. ~30 seconds.
          </p>
        </CardHeader>
        <CardContent>
          <ForwardJobForm
            onSubmit={handleSubmit}
            disabled={!canForward || stream.status === "running"}
          />
          {stream.status === "error" && (
            <p className="mt-2 text-sm text-destructive" role="alert">
              {stream.errorMessage}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Live Phase 1 stream */}
      {stream.status === "running" && stream.startedAt !== null && (
        <Phase1Stream
          startedAt={stream.startedAt}
          completed={stream.completed}
        />
      )}

      {/* Verdict */}
      {stream.status === "complete" && stream.verdict && (
        <VerdictCard
          verdict={stream.verdict}
          bundle={null}
          sessionId={lastSessionIdRef.current ?? undefined}
        />
      )}

      {/* Recent sessions */}
      <SessionList enabled={canForward} />
    </div>
  );
}
