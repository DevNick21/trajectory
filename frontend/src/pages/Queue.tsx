import { useReducer, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play, Trash2 } from "lucide-react";

import { addToQueue, listQueue, removeFromQueue } from "@/lib/api";
import { streamQueueBatch } from "@/lib/sse";
import type { QueueBatchEvent, QueueItem } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/onboarding/Textarea";
import { cn } from "@/lib/utils";

// Batch queue for multi-URL processing (#5). Lives at /queue.
// Pattern: paste URLs (one per line) → add → see queue → Process all.
// The Process button opens an SSE stream and per-job events flow into
// a reducer so the list's status pills update in real time.

// ---------------------------------------------------------------------------
// Per-job live status reducer (in addition to the server-side status)
// ---------------------------------------------------------------------------

type LiveStatus = "idle" | "started" | "completed" | "failed";

interface LiveEntry {
  status: LiveStatus;
  verdict?: "GO" | "NO_GO";
  headline?: string;
  session_id?: string;
  role_title?: string | null;
  company_name?: string | null;
  error?: string;
}

type LiveMap = Record<string, LiveEntry>;

type Action =
  | { kind: "reset" }
  | { kind: "event"; event: QueueBatchEvent };

function reducer(state: LiveMap, action: Action): LiveMap {
  switch (action.kind) {
    case "reset":
      return {};
    case "event": {
      const e = action.event;
      switch (e.type) {
        case "started":
          return { ...state, [e.id]: { status: "started" } };
        case "completed":
          return {
            ...state,
            [e.id]: {
              status: "completed",
              verdict: e.verdict_decision,
              headline: e.verdict_headline,
              session_id: e.session_id,
              role_title: e.role_title,
              company_name: e.company_name,
            },
          };
        case "failed":
          return {
            ...state,
            [e.id]: { status: "failed", error: e.error },
          };
        default:
          return state;
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Queue() {
  const queryClient = useQueryClient();
  const [pasteBox, setPasteBox] = useState("");
  const [pasteError, setPasteError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [live, dispatch] = useReducer(reducer, {});

  const queueQuery = useQuery({
    queryKey: ["queue"],
    queryFn: listQueue,
  });

  const addMutation = useMutation({
    mutationFn: (urls: string[]) => addToQueue(urls),
    onSuccess: () => {
      setPasteBox("");
      setPasteError(null);
      queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
    onError: (err: Error) => setPasteError(err.message),
  });

  const removeMutation = useMutation({
    mutationFn: (id: string) => removeFromQueue(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue"] }),
  });

  const handleAdd = () => {
    const urls = pasteBox
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter((s) => s.startsWith("http://") || s.startsWith("https://"));
    if (urls.length === 0) {
      setPasteError("Paste one or more URLs, one per line.");
      return;
    }
    addMutation.mutate(urls);
  };

  const handleProcess = async () => {
    if (isProcessing) return;
    setIsProcessing(true);
    dispatch({ kind: "reset" });
    try {
      await streamQueueBatch({
        onEvent: (event) => dispatch({ kind: "event", event }),
      });
    } catch (err) {
      // streamQueueBatch only rejects on network — the reducer
      // handles per-job failures inline via `failed` events.
      console.error("batch stream error:", err);
    } finally {
      setIsProcessing(false);
      queryClient.invalidateQueries({ queryKey: ["queue"] });
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
    }
  };

  const queue = queueQuery.data;
  const pendingCount = queue?.pending_count ?? 0;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Add URLs</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Textarea
            rows={5}
            value={pasteBox}
            onChange={(e) => setPasteBox(e.target.value)}
            placeholder={
              "https://example.com/jobs/senior-engineer\nhttps://anotherco.com/careers/role-id\n..."
            }
            disabled={addMutation.isPending}
          />
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
              One URL per line. Duplicates in a single paste are deduped.
            </p>
            <Button onClick={handleAdd} disabled={addMutation.isPending}>
              {addMutation.isPending ? "Adding…" : "Add to queue"}
            </Button>
          </div>
          {pasteError && (
            <p className="text-sm text-destructive" role="alert">
              {pasteError}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Queue</CardTitle>
            <Button
              onClick={handleProcess}
              disabled={isProcessing || pendingCount === 0}
            >
              {isProcessing ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Processing…
                </>
              ) : (
                <>
                  <Play className="mr-2 h-4 w-4" />
                  Process {pendingCount > 0 ? `(${pendingCount})` : "all"}
                </>
              )}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {queueQuery.isPending ? (
            <Skeleton className="h-32 w-full" />
          ) : queueQuery.isError ? (
            <p className="text-sm text-destructive">Failed to load queue.</p>
          ) : !queue || queue.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Empty. Paste some URLs above to get started.
            </p>
          ) : (
            <>
              <p className="mb-3 text-xs text-muted-foreground">
                {queue.pending_count} pending · {queue.done_count} done ·{" "}
                {queue.failed_count} failed · {queue.processing_count} running
              </p>
              <ul className="divide-y">
                {queue.items.map((item) => (
                  <QueueRow
                    key={item.id}
                    item={item}
                    live={live[item.id]}
                    onRemove={() => removeMutation.mutate(item.id)}
                    isRemoving={
                      removeMutation.isPending &&
                      removeMutation.variables === item.id
                    }
                  />
                ))}
              </ul>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<string, string> = {
  pending: "text-muted-foreground",
  processing: "text-foreground",
  started: "text-foreground",
  done: "text-foreground",
  completed: "text-foreground",
  failed: "text-destructive",
};

interface RowProps {
  item: QueueItem;
  live?: LiveEntry;
  onRemove: () => void;
  isRemoving: boolean;
}

function QueueRow({ item, live, onRemove, isRemoving }: RowProps) {
  // Live state (from SSE stream) wins over stored state — otherwise
  // the row shows the refresh-on-completion snapshot.
  const effectiveStatus: string = live?.status ?? item.status;
  const verdict = live?.verdict ?? (item.status === "done" ? undefined : undefined);
  const title = live?.role_title ?? null;
  const company = live?.company_name ?? null;
  const sessionId = live?.session_id ?? item.session_id;

  return (
    <li className="flex items-center gap-3 py-2">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          {effectiveStatus === "processing" || effectiveStatus === "started" ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" />
          ) : null}
          <span
            className={cn(
              "truncate text-sm",
              STATUS_STYLES[effectiveStatus] ?? "text-foreground",
            )}
          >
            {title ?? item.job_url}
            {company && (
              <span className="text-muted-foreground"> · {company}</span>
            )}
          </span>
        </div>
        {live?.headline && (
          <p className="text-xs text-muted-foreground">{live.headline}</p>
        )}
        {(live?.error || item.error) && effectiveStatus === "failed" && (
          <p className="text-xs text-destructive">
            {live?.error ?? item.error}
          </p>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {verdict && (
          <Badge variant={verdict === "GO" ? "success" : "destructive"}>
            {verdict}
          </Badge>
        )}
        {sessionId && (
          <Link
            to={`/sessions/${sessionId}`}
            className="text-xs text-foreground hover:underline"
          >
            Detail
          </Link>
        )}
        <button
          type="button"
          onClick={onRemove}
          disabled={isRemoving}
          title="Remove from queue"
          className="text-muted-foreground hover:text-destructive disabled:opacity-50"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </li>
  );
}
