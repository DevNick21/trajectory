import PickyAvatar, { type PickyState } from "@/components/PickyAvatar";
import { useReducer, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError, getProfile, listSessions } from "@/lib/api";
import { streamForwardJob } from "@/lib/sse";
import type { ForwardJobEvent, SessionListResponse } from "@/lib/types";
import ForwardJobForm from "@/components/ForwardJobForm";
import NotificationBanner from "@/components/NotificationBanner";
import Phase1Stream, { type AgentTiming } from "@/components/Phase1Stream";
import MatrixTransition from "@/components/MatrixTransition";
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

  const pickyState: PickyState =
    stream.status === "running"
      ? "thinking"
      : stream.status === "complete"
        ? (stream.verdict?.decision === "GO" ? "go" : "no_go")
        : stream.status === "error"
          ? "error"
          : "idle";

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
      <MatrixTransition show={stream.status === "complete"} />
      {/* Outcome nudges */}
      {canForward && <NotificationBanner />}

      <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
        {/* Main Action: Forward Job */}
        <div className="md:col-span-8 space-y-6">
          <Card className="border-2 border-primary/20 shadow-2xl shadow-primary/5">
            <CardHeader className="pb-3">
              <CardTitle className="font-serif text-2xl flex items-center gap-3">
                <span className="text-primary animate-pulse">›</span>
                The Judge
              </CardTitle>
              <p className="text-sm text-muted-foreground italic">
                "Feed me a URL. I'll tell you if it's worth your limited lifespan."
              </p>
            </CardHeader>
            <CardContent>
              <ForwardJobForm
                onSubmit={handleSubmit}
                disabled={!canForward || stream.status === "running"}
              />
              {stream.status === "error" && (
                <div className="mt-4 p-3 rounded-md bg-destructive/10 border border-destructive/20 flex items-center gap-2 text-sm text-destructive">
                  <span className="font-bold">SYSTEM ERROR:</span>
                  {stream.errorMessage}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Live Phase 1 stream */}
          {(stream.status === "running" || stream.status === "complete") && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div className="flex flex-col items-center justify-center py-8 bg-card/50 rounded-3xl border border-canvas backdrop-blur-sm">
                <PickyAvatar state={pickyState} className="h-32 w-32 rounded-[2rem]" />
                <div className="mt-6 text-center">
                  <h2 className="font-serif text-xl mb-1">
                    {stream.status === "running" ? "Picky is scrutinizing..." : "The Verdict is In."}
                  </h2>
                  <p className="text-xs font-mono text-muted-foreground tracking-widest uppercase">
                    {stream.status === "running" ? "Parallel Analysis Active" : "Audit Complete"}
                  </p>
                </div>
              </div>
              
              <Phase1Stream
                startedAt={stream.startedAt ?? Date.now()}
                completed={stream.completed}
              />
            </div>
          )}

          {/* Verdict */}
          {stream.status === "complete" && stream.verdict && (
            <div className="animate-in zoom-in-95 duration-500">
              <VerdictCard
                verdict={stream.verdict}
                bundle={null}
                sessionId={lastSessionIdRef.current ?? undefined}
              />
            </div>
          )}
        </div>

        {/* Sidebar Sensors / Profile Gate */}
        <div className="md:col-span-4 space-y-6">
          {/* Profile gate */}
          {profile.isPending ? (
            <Skeleton className="h-40 w-full rounded-2xl" />
          ) : profileMissing ? (
            <Card className="bg-primary/5 border-primary/20 border-t-4 border-t-primary shadow-xl">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-bold uppercase tracking-widest">Context Missing</CardTitle>
              </CardHeader>
              <CardContent className="text-sm space-y-4">
                <p className="text-muted-foreground leading-relaxed">
                  Picky is a world-class researcher, but a blind one. Feed him your history to get precise verdicts.
                </p>
                <a
                  href="/onboarding"
                  className="flex items-center justify-center w-full py-2 bg-primary text-primary-foreground rounded-lg font-bold text-xs hover:scale-[1.02] transition-transform"
                >
                  CALIBRATE PICKY →
                </a>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              <div className="p-4 rounded-2xl bg-secondary/50 border border-canvas">
                <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em] mb-3">Live Sensor Data</p>
                <div className="space-y-2">
                  <div className="flex justify-between items-center text-xs">
                    <span className="text-muted-foreground">Confidence Level</span>
                    <span className="font-mono text-success">98.2%</span>
                  </div>
                  <div className="h-1 w-full bg-background rounded-full overflow-hidden">
                    <div className="h-full bg-success w-[98.2%]" />
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Recent sessions - Sidebar style */}
          <div className="p-1 rounded-2xl bg-card border border-canvas">
            <div className="px-4 py-3 border-b border-canvas">
              <h3 className="text-xs font-bold uppercase tracking-widest">Case Files</h3>
            </div>
            <SessionList enabled={canForward} />
          </div>
        </div>
      </div>
    </div>
  );
}

