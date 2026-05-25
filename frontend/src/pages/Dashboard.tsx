import { MascotSlot, useMascot } from "@/components/MascotContext";
import { useEffect, useReducer, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError, getProfile, getSession, listSessions } from "@/lib/api";
import { streamForwardJob } from "@/lib/sse";
import type { ForwardJobEvent, SessionListResponse, VerdictPayload } from "@/lib/types";
import { isPositiveVerdict, isBlockingVerdict } from "@/lib/verdict";
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

const RECOVERY_KEY = "askpicky_active_session_id";
const STREAM_TIMEOUT_MS = 5 * 60 * 1000; // 5 min — server-side Phase 1 hard deadline

// ---------------------------------------------------------------------------
// SSE state machine — useReducer over the event stream
// ---------------------------------------------------------------------------

type StreamStatus = "idle" | "running" | "complete" | "error";

interface StreamState {
  status: StreamStatus;
  jobUrl: string | null;
  startedAt: number | null;
  active: Record<string, { startedAt: number; failed?: boolean }>;
  completed: Record<string, AgentTiming>;
  verdict: VerdictPayload | null;
  errorMessage: string | null;
}

type Action =
  | { kind: "submit"; jobUrl: string; startedAt: number }
  | { kind: "event"; event: ForwardJobEvent }
  | { kind: "rehydrate"; events: Record<string, unknown>[] }
  | { kind: "clearRecovery" };

const initial: StreamState = {
  status: "idle",
  jobUrl: null,
  startedAt: null,
  active: {},
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
        active: {},
        completed: {},
        verdict: null,
        errorMessage: null,
      };
    case "rehydrate": {
      // Rebuild stream state from persisted progress events.
      // `created_at` from the DB is an ISO datetime string; convert to
      // epoch ms so Phase1Stream timing calculations (subtraction) work.
      const toEpoch = (v: unknown): number => {
        if (typeof v === "number" && v > 0) return v;
        if (typeof v === "string") { const t = new Date(v).getTime(); if (!isNaN(t)) return t; }
        return Date.now();
      };
      let rebuilt = { ...initial, status: "running" as StreamStatus, startedAt: Date.now() };
      for (const e of action.events) {
        const type = e.type as string;
        if (type === "session_started") {
          rebuilt = { ...rebuilt, jobUrl: (e.job_url as string | null) ?? rebuilt.jobUrl, startedAt: toEpoch(e.created_at) };
        } else if (type === "agent_started") {
          rebuilt.active = { ...rebuilt.active, [e.agent as string]: { startedAt: toEpoch(e.created_at) } };
        } else if (type === "agent_complete") {
          const agent = e.agent as string;
          const { [agent]: _, ...rest } = rebuilt.active;
          rebuilt.active = rest;
          rebuilt.completed = { ...rebuilt.completed, [agent]: { completedAt: toEpoch(e.created_at) } };
        } else if (type === "agent_failed") {
          rebuilt.active = { ...rebuilt.active, [e.agent as string]: { startedAt: toEpoch(e.created_at), failed: true } };
        } else if (type === "verdict") {
          rebuilt.status = "complete";
          rebuilt.verdict = e.data as VerdictPayload;
        } else if (type === "error") {
          rebuilt.status = "error";
          rebuilt.errorMessage = ((e.data as Record<string, unknown> | undefined)?.message as string) ?? "Research failed.";
        }
      }
      if (rebuilt.status === "running" && Object.keys(rebuilt.completed).length === 0 && Object.keys(rebuilt.active).length === 0 && state.status !== "idle") {
        return state;
      }
      return rebuilt;
    }
    case "clearRecovery":
      return state.status === "running" || state.status === "complete" || state.status === "error" ? state : initial;
    case "event": {
      const e = action.event;
      switch (e.type) {
        case "session_started":
          return { ...state };
        case "agent_started":
          return {
            ...state,
            active: {
              ...state.active,
              [e.agent]: { startedAt: Date.now() },
            },
          };
        case "agent_complete":
          return {
            ...state,
            active: Object.fromEntries(
              Object.entries(state.active).filter(([agent]) => agent !== e.agent),
            ),
            completed: {
              ...state.completed,
              [e.agent]: { completedAt: Date.now() },
            },
          };
        case "agent_failed":
          return {
            ...state,
            active: {
              ...state.active,
              [e.agent]: { startedAt: state.active[e.agent]?.startedAt ?? Date.now(), failed: true },
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
  const [activeSessionId, setActiveSessionId] = useState<string | null>(() => {
    try { return localStorage.getItem(RECOVERY_KEY); } catch { return null; }
  });

  // Recovery query — fetches session detail when we have a stored
  // active session ID but no live stream. Polls until a verdict or
  // error appears so the dashboard catches up after a refresh.
  const recoveryQuery = useQuery({
    queryKey: ["session", activeSessionId],
    queryFn: () => getSession(activeSessionId!),
    enabled: activeSessionId !== null && stream.status === "idle",
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 4000;
      const verdict = data.verdict as Record<string, unknown> | null | undefined;
      const hasTerminal = verdict != null || data.progress_events.some(
        (e: Record<string, unknown>) => e.type === "error"
      );
      return hasTerminal ? false : 4000;
    },
  });

  // Rehydrate from recovery query when data arrives.
  const prevEventsLenRef = useRef(0);
  useEffect(() => {
    const data = recoveryQuery.data;
    if (!data || stream.status !== "idle") return;
    const events = data.progress_events;
    if (events.length === 0) return;
    if (events.length === prevEventsLenRef.current) return;
    prevEventsLenRef.current = events.length;
    dispatch({ kind: "rehydrate", events });
    if (data.verdict != null || events.some((e: Record<string, unknown>) => e.type === "error")) {
      try { localStorage.removeItem(RECOVERY_KEY); } catch { /* noop */ }
      setActiveSessionId(null);
    }
  }, [recoveryQuery.data, stream.status]);

  // Guard against streams that never emit a terminal event (server crash,
  // network drop without proper teardown). Fire a timeout error so the
  // UI doesn't sit at "Picky is scrutinizing..." forever.
  useEffect(() => {
    if (stream.status !== "running") return;
    const timer = setTimeout(() => {
      dispatch({
        kind: "event",
        event: { type: "error", data: { message: "Research timed out — the server may have restarted. Try again." } },
      });
    }, STREAM_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [stream.status, stream.startedAt]);

  const { setState, setPosition } = useMascot();

  useEffect(() => {
    setPosition("dashboard");
    return () => setPosition("sidebar");
  }, [setPosition]);

  useEffect(() => {
    const label = stream.verdict?.decision;
    const completedCount = Object.keys(stream.completed).length;
    const pickyState =
      stream.status === "running"
        ? (completedCount >= 4 ? "scrutinizing" : "thinking")
        : stream.status === "complete"
          ? (label && isPositiveVerdict(label) ? "go" : label && isBlockingVerdict(label) ? "no_go" : "scrutinizing")
          : stream.status === "error"
            ? "error"
            : "idle";
    setState(pickyState as any);
  }, [stream.status, stream.verdict?.decision, setState]);

  const profileError = profile.error as ApiError | undefined;
  const profileMissing =
    profile.isError && profileError?.code === "profile_not_found";
  const canForward = profile.isSuccess;

  const handleSubmit = async (jobUrl: string) => {
    try { localStorage.removeItem(RECOVERY_KEY); } catch { /* noop */ }
    setActiveSessionId(null);
    dispatch({ kind: "submit", jobUrl, startedAt: Date.now() });
    toast.info("Picky's looking", {
      description: "Nine checks in parallel. Citations on every claim.",
    });
    try {
      await streamForwardJob(jobUrl, {
        onEvent: (event) => {
          dispatch({ kind: "event", event });
          if (event.type === "session_started") {
            try { localStorage.setItem(RECOVERY_KEY, event.session_id); } catch { /* noop */ }
            setActiveSessionId(event.session_id);
            lastSessionIdRef.current = event.session_id;
          }
          if (event.type !== "done") {
            void queryClient.invalidateQueries({ queryKey: ["sessions"] });
          }
          if (event.type === "verdict") {
            try { localStorage.removeItem(RECOVERY_KEY); } catch { /* noop */ }
            setActiveSessionId(null);
            const decision = (event.data?.decision as string | undefined) ?? "?";
            if (isPositiveVerdict(decision)) {
              toast.success("Picky says: apply", {
                description: "Worth your time. Open it to see why.",
              });
            } else if (decision === "ASK_FIRST") {
              toast("Picky says: ask first", {
                description: "Verify a critical detail before applying.",
              });
            } else if (isBlockingVerdict(decision)) {
              toast.warning("Picky says: blocked", {
                description: "Hard blockers found. Open it to see which.",
              });
            } else {
              toast("Picky says: pass", {
                description: "Not worth the time right now. Open to see why.",
              });
            }
          }
        },
        onError: (err) => {
          try { localStorage.removeItem(RECOVERY_KEY); } catch { /* noop */ }
          setActiveSessionId(null);
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
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
      const refreshed = await queryClient.fetchQuery<SessionListResponse>({
        queryKey: ["sessions"],
        queryFn: () => listSessions(),
      });
      lastSessionIdRef.current = refreshed.sessions[0]?.id ?? null;
    }
  };

  const completedCount = Object.keys(stream.completed).length;
  const activeCount = Object.keys(stream.active).length;
  const loadPercentage = stream.status === "running" ? Math.min(95, 10 + completedCount * 10) : (stream.status === "idle" ? 5 : 0);
  const costPercentage = stream.status === "running" ? Math.min(85, completedCount * 9) : (stream.status === "idle" ? 0 : (stream.status === "complete" ? 85 : 0));

  return (
    <div className="space-y-6">
      <MatrixTransition show={stream.status === "complete"} />
      {canForward && <NotificationBanner />}

      <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
        <div className="md:col-span-8 space-y-6">
          <Card className="border-2 border-primary/20 shadow-2xl shadow-primary/5 bg-[#0b101e]">
            <CardHeader className="pb-3">
              <CardTitle className="font-serif text-2xl flex items-center gap-3 text-white">
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

          {(stream.status === "running" || stream.status === "complete") && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div className="flex flex-col items-center justify-center py-8 bg-[#0b101e]/80 rounded-3xl border border-primary/20 backdrop-blur-sm shadow-[0_0_50px_rgba(var(--primary),0.05)]">
                <MascotSlot position="dashboard" className="h-32 w-32 filter drop-shadow-[0_0_15px_rgba(var(--primary),0.5)]" size="lg" />
                <div className="mt-6 text-center">
                  <h2 className="font-serif text-xl mb-1 text-white">
                    {stream.status === "running" ? "Picky is scrutinizing..." : "The Verdict is In."}
                  </h2>
                  <p className="text-xs font-mono text-primary tracking-widest uppercase">
                    {stream.status === "running" ? "Parallel Analysis Active" : "Audit Complete"}
                  </p>
                </div>
              </div>
              
              <Phase1Stream
                startedAt={stream.startedAt ?? Date.now()}
                completed={stream.completed}
                active={stream.active}
              />
            </div>
          )}

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

        <div className="md:col-span-4 space-y-6">
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
              <div className="p-5 rounded-2xl bg-[#0b101e] border border-primary/20 shadow-lg">
                <h3 className="text-[10px] font-bold text-primary uppercase tracking-[0.2em] mb-4 flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
                  System Overview
                </h3>

                <div className="grid grid-cols-2 gap-4 mb-6">
                  <div className="bg-[#151b2b] p-3 rounded-lg border border-primary/10">
                    <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1 flex items-center gap-1">
                      <span className="text-primary">⚙</span> LLM Load
                    </p>
                    <p className="text-xl font-mono text-white">{loadPercentage}%</p>
                    <div className="mt-2 h-1 w-full bg-black rounded-full overflow-hidden">
                      <div className="h-full bg-primary transition-all duration-500" style={{ width: `${loadPercentage}%` }} />
                    </div>
                  </div>
                  <div className="bg-[#151b2b] p-3 rounded-lg border border-primary/10">
                    <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1 flex items-center gap-1">
                      <span className="text-success">$</span> Budget
                    </p>
                    <p className="text-xl font-mono text-white">{costPercentage}%</p>
                    <div className="mt-2 h-1 w-full bg-black rounded-full overflow-hidden">
                      <div className="h-full bg-success transition-all duration-500" style={{ width: `${costPercentage}%` }} />
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  <div>
                    <div className="flex justify-between items-center text-xs mb-1">
                      <span className="text-muted-foreground font-mono">DeepSeek V4 Flash</span>
                      <span className="font-mono text-primary text-[10px] uppercase tracking-widest">{stream.status === "running" ? (activeCount > 0 ? `${activeCount} Active` : "Running") : "Standby"}</span>
                    </div>
                    <div className="h-1 w-full bg-black rounded-full overflow-hidden">
                      <div className="h-full bg-primary transition-all duration-500" style={{ width: stream.status === "running" ? '80%' : '0%' }} />
                    </div>
                  </div>
                  <div>
                    <div className="flex justify-between items-center text-xs mb-1">
                      <span className="text-muted-foreground font-mono">GPT-5.4 (Verdict)</span>
                      <span className="font-mono text-success text-[10px] uppercase tracking-widest">{stream.status === "complete" ? "Complete" : (stream.status === "running" && completedCount >= 8 ? "Active" : "Standby")}</span>
                    </div>
                    <div className="h-1 w-full bg-black rounded-full overflow-hidden">
                      <div className="h-full bg-success transition-all duration-500" style={{ width: stream.status === "complete" ? '100%' : (stream.status === "running" && completedCount >= 8 ? '40%' : '0%') }} />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

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
