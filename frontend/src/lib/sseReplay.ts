// Deterministic SSE replay for the demo recording.
//
// Toggled by VITE_SSE_REPLAY=1 in .env.local (or `?replay=1` in the URL).
// When active, streamForwardJob() is replaced with a canned event
// sequence that runs in ~11s with realistic ticking cadence — fixing the
// 12-second hero shot's timing without depending on a live forward_job
// taking exactly 12s.
//
// All citation kinds appear in the verdict payload so the
// `verdict-citation.mp4` shot can be filmed against the same replay
// take: a `gov_data` chip for the Sponsor Register, a `url_snippet`
// chip with verbatim text, and a `career_entry` chip.

import type { ForwardJobEvent } from "./types";

interface CannedEvent {
  /** Milliseconds from stream start. */
  delayMs: number;
  event: ForwardJobEvent;
}

// Cadence chosen to match real Phase 1 latency profile: parquet lookups
// fast, then scraper, then Sonnet agents, then Opus verdict. Order
// follows PHASE_1_AGENTS so the visible ticks march down the list.
const CAPITAL_ON_TAP_GO: CannedEvent[] = [
  { delayMs:   500, event: { type: "agent_complete", agent: "phase_1_jd_extractor" } },
  { delayMs:  1100, event: { type: "agent_complete", agent: "phase_1_company_scraper_summariser" } },
  { delayMs:  1500, event: { type: "agent_complete", agent: "companies_house" } },
  { delayMs:  2400, event: { type: "agent_complete", agent: "sponsor_register" } },
  { delayMs:  3000, event: { type: "agent_complete", agent: "soc_check" } },
  { delayMs:  4600, event: { type: "agent_complete", agent: "salary_data" } },
  { delayMs:  7100, event: { type: "agent_complete", agent: "reviews" } },
  { delayMs:  8400, event: { type: "agent_complete", agent: "phase_1_ghost_job_jd_scorer" } },
  { delayMs:  9300, event: { type: "agent_complete", agent: "phase_1_red_flags" } },
  {
    delayMs: 10800,
    event: {
      type: "verdict",
      data: {
        decision: "GO",
        confidence_pct: 88,
        headline: "Strong fit — sponsor A-rated, salary clears the threshold",
        reasoning: [
          {
            claim: "Capital on Tap is an A-rated Skilled Worker sponsor",
            supporting_evidence:
              "Listed under their registered legal entity on the Home Office sponsor register.",
            citation: {
              kind: "gov_data",
              data_field: "sponsor_register.status",
              data_value: "LISTED · Worker (A rating)",
            },
          },
          {
            claim: "Posted salary clears the SOC going rate",
            supporting_evidence:
              "Greenhouse JD states £75,000–£95,000 base; SOC 2136 going rate is £49,400.",
            citation: {
              kind: "url_snippet",
              url: "https://job-boards.greenhouse.io/capitalontap/jobs/8520481002",
              verbatim_snippet: "£75,000–£95,000 base + equity",
            },
          },
          {
            claim: "Backend + payments experience matches the JD core requirement",
            supporting_evidence:
              "Three years building payment-rails infrastructure at a fintech.",
            citation: {
              kind: "career_entry",
              entry_id: "demo-payments-rails-001",
            },
          },
        ],
        hard_blockers: [],
        stretch_concerns: [],
      },
    },
  },
  { delayMs: 11000, event: { type: "done" } },
];

export function isReplayActive(): boolean {
  // Accept either the build-time env or a runtime ?replay=1 query param
  // so you can toggle without rebuilding during a recording session.
  if (typeof window !== "undefined") {
    const params = new URLSearchParams(window.location.search);
    if (params.get("replay") === "1") return true;
  }
  // Vite injects env at build time; cast since the project doesn't ship
  // a vite-env.d.ts type augmentation.
  const env = (import.meta as unknown as { env?: Record<string, string> }).env;
  return env?.VITE_SSE_REPLAY === "1";
}

interface ReplayOptions {
  signal?: AbortSignal;
  onEvent: (event: ForwardJobEvent) => void;
}

export async function replayForwardJob(opts: ReplayOptions): Promise<void> {
  const start = performance.now();
  for (const c of CAPITAL_ON_TAP_GO) {
    if (opts.signal?.aborted) return;
    const elapsed = performance.now() - start;
    const wait = Math.max(0, c.delayMs - elapsed);
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(resolve, wait);
      const abort = () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      };
      opts.signal?.addEventListener("abort", abort, { once: true });
    });
    if (opts.signal?.aborted) return;
    opts.onEvent(c.event);
  }
}
