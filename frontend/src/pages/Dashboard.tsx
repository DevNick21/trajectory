import { useQuery } from "@tanstack/react-query";
import { ApiError, getHealth, getProfile, listSessions } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";

// Wave 6 stub. Wave 7 builds the real ForwardJobForm + Phase1Stream +
// VerdictCard + SessionList. For now this page just proves the API
// glue works: it pings /health, fetches /api/profile, lists recent
// sessions, and shows whatever the backend returns.

export default function Dashboard() {
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth });
  const profile = useQuery({ queryKey: ["profile"], queryFn: getProfile, retry: false });
  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: () => listSessions(),
    enabled: profile.isSuccess,
  });

  const profileError = profile.error as ApiError | undefined;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Backend status</CardTitle>
        </CardHeader>
        <CardContent>
          {health.isPending ? (
            <Skeleton className="h-4 w-48" />
          ) : health.isError ? (
            <p className="text-destructive">API unreachable.</p>
          ) : (
            <p className="text-sm text-muted-foreground">
              {health.data.service} v{health.data.version} —{" "}
              <span className="text-foreground">{health.data.status}</span>
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
        </CardHeader>
        <CardContent>
          {profile.isPending ? (
            <Skeleton className="h-4 w-64" />
          ) : profile.isError && profileError?.code === "profile_not_found" ? (
            <p className="text-sm">
              No profile yet —{" "}
              <a href="/onboarding" className="underline">
                complete onboarding
              </a>{" "}
              to get started.
            </p>
          ) : profile.isError ? (
            <p className="text-destructive">
              {profileError?.message ?? "Profile failed to load."}
            </p>
          ) : (
            <p className="text-sm">
              Signed in as <span className="font-medium">{profile.data.name}</span>{" "}
              <span className="text-muted-foreground">({profile.data.user_type})</span>
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent sessions</CardTitle>
        </CardHeader>
        <CardContent>
          {sessions.isPending && profile.isSuccess ? (
            <Skeleton className="h-20 w-full" />
          ) : sessions.data?.sessions.length ? (
            <ul className="divide-y">
              {sessions.data.sessions.map((s) => (
                <li key={s.id} className="flex items-center justify-between py-2">
                  <a
                    href={`/sessions/${s.id}`}
                    className="text-sm hover:underline"
                  >
                    {s.role_title ?? s.job_url ?? s.id}
                    {s.company_name && (
                      <span className="text-muted-foreground"> · {s.company_name}</span>
                    )}
                  </a>
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
              No sessions yet. Wave 7 adds the forward-job form.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
