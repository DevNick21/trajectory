// SSE wrapper. Two flavours:
//
//   - subscribeSSE(url, options): native EventSource for GET endpoints.
//     EventSource automatically reconnects on network blips, which is
//     usually what we want for live progress.
//
//   - postSSE(url, body, onEvent, options): POST + streaming response,
//     manually parsed. EventSource is GET-only — the spec doesn't allow
//     a request body. Both forward_job and full_prep are POST endpoints,
//     so they need this path.
//
// The parsed event matches the discriminated unions in lib/types.ts;
// the caller's onEvent gets a typed value when the message line is
// valid JSON.

import type { ForwardJobEvent, FullPrepEvent, QueueBatchEvent } from "./types";
import { isReplayActive, replayForwardJob } from "./sseReplay";

interface PostSSEOptions {
  signal?: AbortSignal;
  onError?: (error: Error) => void;
}

async function postSSE<TEvent>(
  url: string,
  body: unknown,
  onEvent: (event: TEvent) => void,
  options: PostSSEOptions = {},
): Promise<void> {
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    signal: options.signal,
  });

  if (!resp.ok) {
    throw new Error(`POST ${url} returned ${resp.status}`);
  }
  if (!resp.body) {
    throw new Error(`POST ${url} returned no body`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });

      // SSE messages are separated by blank lines (\n\n). Split on
      // double-newline; keep the trailing partial in the buffer.
      const messages = buffer.split("\n\n");
      buffer = messages.pop() ?? "";

      for (const raw of messages) {
        const dataLine = raw
          .split("\n")
          .find((line) => line.startsWith("data:"));
        if (!dataLine) continue;
        const payload = dataLine.slice("data:".length).trim();
        if (!payload) continue;
        try {
          onEvent(JSON.parse(payload) as TEvent);
        } catch (err) {
          options.onError?.(err as Error);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

// ---------------------------------------------------------------------------
// Public entry points — typed per stream
// ---------------------------------------------------------------------------

export interface ForwardJobOptions extends PostSSEOptions {
  onEvent: (event: ForwardJobEvent) => void;
}

export const streamForwardJob = (jobUrl: string, opts: ForwardJobOptions) => {
  // Demo recording shortcut — bypass the real API and emit a canned
  // event sequence with deterministic timing. Active when
  // VITE_SSE_REPLAY=1 or the URL carries ?replay=1. Same shape as the
  // live stream so the dashboard reducer doesn't notice the difference.
  if (isReplayActive()) {
    return replayForwardJob({ onEvent: opts.onEvent, signal: opts.signal });
  }
  return postSSE<ForwardJobEvent>(
    "/api/sessions/forward_job",
    { job_url: jobUrl },
    opts.onEvent,
    { signal: opts.signal, onError: opts.onError },
  );
};

export interface FullPrepOptions extends PostSSEOptions {
  onEvent: (event: FullPrepEvent) => void;
}

export const streamFullPrep = (sessionId: string, opts: FullPrepOptions) =>
  postSSE<FullPrepEvent>(
    `/api/sessions/${encodeURIComponent(sessionId)}/full_prep`,
    {},
    opts.onEvent,
    { signal: opts.signal, onError: opts.onError },
  );

export interface QueueBatchOptions extends PostSSEOptions {
  onEvent: (event: QueueBatchEvent) => void;
}

export const streamQueueBatch = (opts: QueueBatchOptions) =>
  postSSE<QueueBatchEvent>(
    "/api/queue/process",
    {},
    opts.onEvent,
    { signal: opts.signal, onError: opts.onError },
  );
