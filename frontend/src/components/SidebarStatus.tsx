// Sidebar bottom-of-rail status block. Pulls real session data so the
// number isn't lying. Falls back to honest "fresh start" copy when the
// user has no history yet — keeps the §4 "honest about uncertainty"
// rule intact.

import { useQuery } from "@tanstack/react-query";
import { listSessions } from "@/lib/api";

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

export default function SidebarStatus() {
  const sessions = useQuery({
    queryKey: ["sessions", "sidebar-status"],
    queryFn: () => listSessions(50),
    staleTime: 30_000,
  });

  let body = "Picky is ready. Forward a role to get started.";

  if (sessions.isLoading) {
    body = "Loading session history…";
  } else if (sessions.data?.sessions?.length) {
    const cutoff = Date.now() - WEEK_MS;
    const recent = sessions.data.sessions.filter(
      (s) => new Date(s.created_at).getTime() >= cutoff,
    );
    const greens = recent.filter((s) => s.verdict === "GO").length;
    const reds = recent.filter((s) => s.verdict === "NO_GO").length;
    if (recent.length === 0) {
      body = `${sessions.data.sessions.length} role(s) on file. Nothing forwarded this week.`;
    } else {
      body = `${recent.length} role(s) checked this week — ${greens} go, ${reds} no-go.`;
    }
  }

  return (
    <div className="bg-primary/5 rounded-lg p-3 border border-primary/10">
      <p className="text-[10px] text-primary font-bold uppercase tracking-tighter mb-1">
        Status
      </p>
      <p className="text-xs text-muted-foreground leading-relaxed">{body}</p>
    </div>
  );
}
