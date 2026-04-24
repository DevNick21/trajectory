import { useEffect, useState } from "react";
import { Check, Circle, Loader2 } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PHASE_1_AGENTS, labelFor } from "@/lib/constants";
import { cn } from "@/lib/utils";

export interface AgentTiming {
  /** ms since epoch when the agent_complete event arrived. */
  completedAt: number;
}

interface Props {
  /** ms since epoch when the stream opened (for elapsed-time math). */
  startedAt: number;
  /** Map: agent name → timing record. Agents not in the map are pending. */
  completed: Record<string, AgentTiming>;
}

// Three states per row:
//   ✓ done    — `agent_complete` arrived
//   ⟳ active  — first agent in PHASE_1_AGENTS not yet completed
//                (Wave 4 contract: only complete events flow today;
//                  inferred running-state matches what the user
//                  experiences as "this is what's working now")
//   ○ pending — everything after the active row
export default function Phase1Stream({ startedAt, completed }: Props) {
  const firstPendingIndex = PHASE_1_AGENTS.findIndex(
    (name) => !(name in completed),
  );
  const activeIndex = firstPendingIndex === -1 ? null : firstPendingIndex;
  const allDone = firstPendingIndex === -1;

  // Tick the active row's elapsed display every 200ms so the spinner
  // reads as alive. Stops when all agents are done — no point burning
  // re-renders after that.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (allDone) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 200);
    return () => window.clearInterval(id);
  }, [allDone]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {allDone ? "Research complete" : "Running research…"}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {PHASE_1_AGENTS.map((agent, i) => {
            const timing = completed[agent];
            const isDone = Boolean(timing);
            const isActive = activeIndex === i;
            const elapsedMs = timing
              ? timing.completedAt - startedAt
              : isActive
                ? Date.now() - startedAt
                : null;
            return (
              <li
                key={agent}
                className={cn(
                  "flex items-center justify-between text-sm",
                  isDone ? "text-foreground" : "text-muted-foreground",
                )}
              >
                <span className="flex items-center gap-2">
                  {isDone ? (
                    <Check className="h-4 w-4 text-success" aria-hidden />
                  ) : isActive ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : (
                    <Circle className="h-4 w-4" aria-hidden />
                  )}
                  {labelFor(agent)}
                </span>
                {elapsedMs !== null && (
                  <span className="tabular-nums text-xs">
                    {(elapsedMs / 1000).toFixed(1)}s
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
