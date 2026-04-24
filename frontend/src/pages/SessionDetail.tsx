import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getSession } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

// Wave 6 stub. Wave 8 adds <VerdictEvidence /> + <PackGenerator /> +
// <FileList /> + <CostBreakdown />.

export default function SessionDetail() {
  const { id = "" } = useParams();
  const session = useQuery({
    queryKey: ["session", id],
    queryFn: () => getSession(id),
    enabled: Boolean(id),
  });

  if (session.isPending) {
    return <Skeleton className="h-64 w-full" />;
  }
  if (session.isError || !session.data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Session not found</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            The session either doesn't exist or isn't yours.
          </p>
        </CardContent>
      </Card>
    );
  }

  const s = session.data;
  const verdict = s.verdict as { decision?: "GO" | "NO_GO"; headline?: string } | null;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>{s.job_url ?? s.id}</CardTitle>
            {verdict?.decision && (
              <Badge
                variant={verdict.decision === "GO" ? "success" : "destructive"}
              >
                {verdict.decision}
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {verdict?.headline && (
            <p className="text-sm">{verdict.headline}</p>
          )}
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-muted-foreground">Intent</dt>
              <dd>{s.intent}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Created</dt>
              <dd>{new Date(s.created_at).toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Cost so far</dt>
              <dd>${s.cost_summary.total_usd.toFixed(4)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Generated files</dt>
              <dd>{s.generated_files.length}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      {s.generated_files.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Files</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="divide-y">
              {s.generated_files.map((f) => (
                <li key={f.filename} className="flex items-center justify-between py-2">
                  <a href={f.download_url} className="text-sm hover:underline">
                    {f.filename}
                  </a>
                  <span className="text-xs text-muted-foreground">
                    {(f.size_bytes / 1024).toFixed(1)} KB · {f.kind}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
