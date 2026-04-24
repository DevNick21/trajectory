import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { listSessions } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

interface Props {
  enabled?: boolean;
}

export default function SessionList({ enabled = true }: Props) {
  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: () => listSessions(),
    enabled,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent sessions</CardTitle>
      </CardHeader>
      <CardContent>
        {!enabled ? (
          <p className="text-sm text-muted-foreground">
            Onboard first to see sessions.
          </p>
        ) : sessions.isPending ? (
          <Skeleton className="h-20 w-full" />
        ) : sessions.isError ? (
          <p className="text-sm text-destructive">Failed to load sessions.</p>
        ) : sessions.data?.sessions.length ? (
          <ul className="divide-y">
            {sessions.data.sessions.map((s) => (
              <li
                key={s.id}
                className="flex items-center justify-between gap-3 py-2"
              >
                <Link
                  to={`/sessions/${s.id}`}
                  className="flex-1 truncate text-sm hover:underline"
                >
                  {s.role_title ?? s.job_url ?? s.id}
                  {s.company_name && (
                    <span className="text-muted-foreground"> · {s.company_name}</span>
                  )}
                </Link>
                {s.verdict && (
                  <Badge
                    variant={s.verdict === "GO" ? "success" : "destructive"}
                  >
                    {s.verdict}
                  </Badge>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            Forward a job URL above to start a session.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
