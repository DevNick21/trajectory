// Sidebar bottom-of-rail status block. Pulls real session data so the
// number isn't lying. Falls back to honest "fresh start" copy when the
// user has no history yet — keeps the §4 "honest about uncertainty"
// rule intact.

import { useQuery } from "@tanstack/react-query";
import { listSessions } from "@/lib/api";
import { Activity } from "lucide-react";
import { cn } from "@/lib/utils";
import { isPositiveVerdict, isBlockingVerdict } from "@/lib/verdict";

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

export default function SidebarStatus() {
  const sessions = useQuery({
    queryKey: ["sessions", "sidebar-status"],
    queryFn: () => listSessions(50),
    staleTime: 5_000,
  });

  let stats = { total: 0, recent: 0, apply: 0, blocked: 0 };
  let statusText = "Ready for Ingest";
  let isLoading = sessions.isLoading;

  if (sessions.data?.sessions?.length) {
    const cutoff = Date.now() - WEEK_MS;
    const all = sessions.data.sessions;
    const recent = all.filter(
      (s) => new Date(s.created_at).getTime() >= cutoff,
    );
    stats = {
      total: all.length,
      recent: recent.length,
      apply: recent.filter((s) => s.verdict && isPositiveVerdict(s.verdict)).length,
      blocked: recent.filter((s) => s.verdict && isBlockingVerdict(s.verdict)).length
    };
    statusText = recent.length > 0 ? "Active Surveillance" : "Archive Standby";
  }

  return (
    <div className="bg-background/40 rounded-xl p-4 border border-canvas shadow-inner group relative overflow-hidden">
      <div className="absolute top-0 left-0 w-1 h-full bg-primary/20 group-hover:bg-primary/40 transition-colors" />
      
      <div className="flex items-center justify-between mb-3 relative z-10">
        <div className="flex items-center gap-2">
           <Activity className={cn("h-3 w-3 text-primary", isLoading && "animate-pulse")} />
           <span className="text-[9px] font-mono font-bold uppercase tracking-[0.2em] text-primary">{statusText}</span>
        </div>
        <div className="flex gap-1">
           {[...Array(3)].map((_, i) => (
             <div key={i} className={cn("w-1 h-1 rounded-full bg-primary/20", isLoading && "animate-pulse")} style={{ animationDelay: `${i * 200}ms` }} />
           ))}
        </div>
      </div>

      <div className="space-y-3 relative z-10">
        <div className="grid grid-cols-2 gap-2">
          <StatBox label="Archive" value={stats.total} />
          <StatBox label="Weekly" value={stats.recent} />
        </div>
        
        {stats.recent > 0 && (
          <div className="flex gap-2">
            <div className="h-1 flex-1 bg-success/20 rounded-full overflow-hidden">
              <div className="h-full bg-success" style={{ width: `${(stats.apply / stats.recent) * 100}%` }} />
            </div>
            <div className="h-1 flex-1 bg-destructive/20 rounded-full overflow-hidden">
              <div className="h-full bg-destructive" style={{ width: `${(stats.blocked / stats.recent) * 100}%` }} />
            </div>
          </div>
        )}

        <p className="text-[10px] text-muted-foreground font-mono leading-tight uppercase tracking-tight">
          {isLoading ? "Synchronizing history..." : stats.total === 0 ? "Awaiting first target URL." : `Lab-ID: PIKY-${stats.total.toString().padStart(4, '0')}`}
        </p>
      </div>
    </div>
  );
}

function StatBox({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-secondary/20 rounded border border-canvas p-1.5 flex flex-col gap-0.5">
      <span className="text-[7px] font-mono font-bold uppercase tracking-widest text-muted-foreground">{label}</span>
      <span className="text-xs font-mono font-bold text-foreground tabular-nums">{value.toString().padStart(2, '0')}</span>
    </div>
  );
}
