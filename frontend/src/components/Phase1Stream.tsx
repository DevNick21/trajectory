import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PHASE_1_AGENTS, labelFor } from "@/lib/constants";
import { cn } from "@/lib/utils";

export interface AgentTiming {
  completedAt: number;
}

interface Props {
  startedAt: number;
  completed: Record<string, AgentTiming>;
  active: Record<string, { startedAt: number; failed?: boolean }>;
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

// Helper to provide fake descriptions for the communications log feel
function getLogDescription(agentName: string) {
  switch (agentName) {
    case "company_scraper_summariser": return "Fetching corporate intelligence and extracting core values.";
    case "jd_extractor": return "Parsing job description requirements and structural data.";
    case "red_flags_detector": return "Scanning for pattern of negative reviews and recent news.";
    case "ghost_job_scorer": return "Analyzing boilerplate ratio and specificity signals.";
    case "gazette_insolvency": return "Cross-referencing Companies House and insolvency records.";
    case "salary_data_fetcher": return "Aggregating market percentile data for given SOC code.";
    case "sponsor_register_check": return "Verifying active status on UK Visa Sponsor list.";
    case "soc_code_matcher": return "Matching job duties to standard occupational classification.";
    default: return `Running analysis module: ${agentName}`;
  }
}

export default function Phase1Stream({ startedAt, completed, active }: Props) {
  const firstPendingIndex = PHASE_1_AGENTS.findIndex(
    (name) => !(name in completed),
  );
  const activeIndex = firstPendingIndex === -1 ? null : firstPendingIndex;
  const allDone = firstPendingIndex === -1;

  const [, setTick] = useState(0);
  useEffect(() => {
    if (allDone) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 200);
    return () => window.clearInterval(id);
  }, [allDone]);

  return (
    <Card className="bg-[#0b101e] border-primary/20 font-sans shadow-2xl overflow-hidden rounded-xl">
      <CardHeader className="border-b border-primary/10 bg-[#0f172a] py-4 relative">
        <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-primary/50 to-transparent opacity-50" />
        <CardTitle className="text-sm flex items-center justify-between text-white font-bold tracking-wide">
          <div className="flex items-center gap-3">
            <span className="relative flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3 w-3 bg-primary"></span>
            </span>
            Communications Log
          </div>
          <div className="text-[10px] uppercase text-primary/70 font-mono tracking-widest border border-primary/20 px-2 py-0.5 rounded-full bg-primary/5">
            {allDone ? "All Modules Complete" : "Live Feed"}
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <motion.div
          className="divide-y divide-primary/5"
          variants={listVariants}
          initial="initial"
          animate="animate"
        >
          {PHASE_1_AGENTS.map((agent, i) => {
            const timing = completed[agent];
            const activeTiming = active[agent];
            const isDone = Boolean(timing);
            const isActive = Boolean(activeTiming) || activeIndex === i;
            const elapsedMs = timing
              ? timing.completedAt - startedAt
              : activeTiming
                ? Date.now() - activeTiming.startedAt
                : isActive
                  ? Date.now() - startedAt
                : null;
            return (
              <motion.div
                key={agent}
                variants={rowVariants}
                layout
                className={cn(
                  "flex items-center justify-between px-6 py-4 transition-all duration-300",
                  isDone ? "bg-transparent text-white" : isActive ? "bg-primary/5 text-white shadow-[inset_2px_0_0_0_hsl(var(--primary))]" : "text-muted-foreground opacity-50 bg-[#080c17]",
                )}
              >
                <div className="flex items-start gap-4">
                  <div className="mt-1">
                    <AnimatePresence mode="wait" initial={false}>
                      {isDone ? (
                        <motion.div
                          key="done"
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          className="h-4 w-4 rounded-full bg-white/20 flex items-center justify-center border border-white/10"
                        >
                          <div className="h-2 w-2 rounded-full bg-white" />
                        </motion.div>
                      ) : activeTiming?.failed ? (
                        <motion.div
                          key="failed"
                          initial={{ scale: 0.9 }}
                          animate={{ scale: 1 }}
                          className="h-4 w-4 rounded-full bg-destructive/20 flex items-center justify-center border border-destructive/40"
                        >
                          <div className="h-2 w-2 rounded-full bg-destructive" />
                        </motion.div>
                      ) : activeTiming ? (
                        <motion.div
                          key="active"
                          className="h-4 w-4 rounded-full border-2 border-primary border-t-transparent animate-spin"
                        />
                      ) : isActive ? (
                        <motion.div
                          key="pending-active"
                          className="h-4 w-4 rounded-full border-2 border-primary/50 border-t-transparent animate-spin opacity-60"
                        />
                      ) : (
                        <div className="h-4 w-4 rounded-full border-2 border-muted-foreground/30" />
                      )}
                    </AnimatePresence>
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-sm tracking-tight">{labelFor(agent)}</span>
                      {isDone ? null : activeTiming?.failed ? <span className="text-[9px] uppercase tracking-widest text-destructive bg-destructive/10 px-1 rounded">Failed</span> : activeTiming ? <span className="text-[9px] uppercase tracking-widest text-primary animate-pulse bg-primary/10 px-1 rounded">Processing</span> : isActive ? <span className="text-[9px] uppercase tracking-widest text-primary/70 bg-primary/5 px-1 rounded">Queued</span> : null}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{getLogDescription(agent)}</p>
                  </div>
                </div>
                
                <div className="flex items-center gap-4 text-xs font-mono">
                  {elapsedMs !== null && (
                    <span className={cn("tabular-nums opacity-80", isDone ? "text-muted-foreground" : "text-primary")}>
                      {new Date(elapsedMs).toISOString().substring(14, 23)}
                    </span>
                  )}
                  {isDone && <span className="text-primary rounded-full w-2 h-2 bg-primary ml-2 shadow-[0_0_8px_rgba(var(--primary),0.8)]" />}
                </div>
              </motion.div>
            );
          })}
        </motion.div>
      </CardContent>
    </Card>
  );
}
