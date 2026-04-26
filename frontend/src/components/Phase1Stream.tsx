import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
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

const listVariants = {
  animate: { transition: { staggerChildren: 0.06 } },
} as const;

const rowVariants = {
  initial: { opacity: 0, y: 4 },
  animate: {
    opacity: 1,
    y: 0,
    transition: { type: "spring", stiffness: 300, damping: 24 },
  },
} as const;

// Three states per row:
//   ✓ done    — `agent_complete` arrived
//   ⟳ active  — first agent in PHASE_1_AGENTS not yet completed
//   ○ pending — everything after the active row
export default function Phase1Stream({ startedAt, completed }: Props) {
  const firstPendingIndex = PHASE_1_AGENTS.findIndex(
    (name) => !(name in completed),
  );
  const activeIndex = firstPendingIndex === -1 ? null : firstPendingIndex;
  const allDone = firstPendingIndex === -1;

  // Tick the active row's elapsed display every 200ms so the spinner
  // reads as alive. Stops when all agents are done.
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
        <motion.ul
          className="space-y-2"
          variants={listVariants}
          initial="initial"
          animate="animate"
        >
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
              <motion.li
                key={agent}
                variants={rowVariants}
                layout
                className={cn(
                  "flex items-center justify-between text-sm",
                  isDone ? "text-foreground" : "text-muted-foreground",
                )}
              >
                <span className="flex items-center gap-2">
                  <AnimatePresence mode="wait" initial={false}>
                    {isDone ? (
                      <motion.span
                        key="done"
                        initial={{ scale: 0, rotate: -30, opacity: 0 }}
                        animate={{ scale: 1, rotate: 0, opacity: 1 }}
                        exit={{ scale: 0, opacity: 0 }}
                        transition={{ type: "spring", stiffness: 400, damping: 18 }}
                        className="inline-flex"
                      >
                        <Check className="h-4 w-4 text-success" aria-hidden />
                      </motion.span>
                    ) : isActive ? (
                      <motion.span
                        key="active"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.15 }}
                        className="inline-flex"
                      >
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                      </motion.span>
                    ) : (
                      <motion.span
                        key="pending"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 0.5 }}
                        exit={{ opacity: 0 }}
                        className="inline-flex"
                      >
                        <Circle className="h-4 w-4" aria-hidden />
                      </motion.span>
                    )}
                  </AnimatePresence>
                  {labelFor(agent)}
                </span>
                {elapsedMs !== null && (
                  <motion.span
                    className="tabular-nums text-xs"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 0.1 }}
                  >
                    {(elapsedMs / 1000).toFixed(1)}s
                  </motion.span>
                )}
              </motion.li>
            );
          })}
        </motion.ul>
      </CardContent>
    </Card>
  );
}
