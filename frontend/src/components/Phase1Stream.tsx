import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";

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

  // Tick the active row's elapsed display every 200ms
  const [, setTick] = useState(0);
  useEffect(() => {
    if (allDone) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 200);
    return () => window.clearInterval(id);
  }, [allDone]);

  return (
    <Card className="bg-black border-primary/30 font-mono shadow-[0_0_30px_rgba(var(--primary),0.1)]">
      <CardHeader className="border-b border-primary/20 bg-primary/5 py-3">
        <CardTitle className="text-xs flex items-center gap-2 text-primary uppercase tracking-[0.2em]">
          <span className="h-2 w-2 rounded-full bg-primary animate-pulse" />
          Neural Link: Analysis In Progress
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <motion.div
          className="divide-y divide-primary/10"
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
              <motion.div
                key={agent}
                variants={rowVariants}
                layout
                className={cn(
                  "flex items-center justify-between px-6 py-3 text-[10px] sm:text-xs transition-colors",
                  isDone ? "bg-primary/5 text-primary" : isActive ? "bg-white/5 text-foreground" : "text-muted-foreground opacity-40",
                )}
              >
                <div className="flex items-center gap-3">
                  <div className="w-4 flex justify-center">
                    <AnimatePresence mode="wait" initial={false}>
                      {isDone ? (
                        <motion.span
                          key="done"
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          className="text-success"
                        >
                          ●
                        </motion.span>
                      ) : isActive ? (
                        <motion.span
                          key="active"
                          animate={{ rotate: 360 }}
                          transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                        >
                          ○
                        </motion.span>
                      ) : (
                        <span>·</span>
                      )}
                    </AnimatePresence>
                  </div>
                  <span className={cn(isActive && "font-bold tracking-tight")}>
                    {isActive && "> "}
                    {labelFor(agent).toUpperCase()}
                  </span>
                </div>
                
                <div className="flex items-center gap-4">
                  {isActive && (
                    <span className="text-[10px] animate-pulse">PROCESSING...</span>
                  )}
                  {elapsedMs !== null && (
                    <span className="tabular-nums opacity-60">
                      {(elapsedMs / 1000).toFixed(2)}s
                    </span>
                  )}
                </div>
              </motion.div>
            );
          })}
        </motion.div>
      </CardContent>
    </Card>
  );
}
