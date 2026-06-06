import { Link, useNavigate, useParams } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  deleteApplication,
  getApplication,
  refreshApplicationEvidence,
  updateApplication,
} from "@/lib/api";
import type { ApplicationRecord, LocalEvidenceCheckpoint } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/onboarding/Textarea";

const STATUS_TONE: Record<LocalEvidenceCheckpoint["status"], string> = {
  matched: "bg-success/10 text-success border-success/20",
  missing: "bg-destructive/10 text-destructive border-destructive/20",
  needs_profile: "bg-muted text-muted-foreground border-border",
  needs_confirmation: "bg-primary/10 text-primary border-primary/20",
};

function cleanSessionId(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function label(value: string): string {
  return value.replace(/_/g, " ");
}

function evidenceCounts(record: ApplicationRecord | null) {
  const snapshot = record?.evidence_snapshot ?? record?.local_analysis;
  const checkpoints = snapshot?.evidence_checkpoints ?? [];
  return {
    matched: checkpoints.filter((item) => item.status === "matched").length,
    missing: checkpoints.filter(
      (item) => item.status === "missing" || item.status === "needs_profile",
    ).length,
    confirmation: checkpoints.filter((item) => item.status === "needs_confirmation").length,
  };
}

export default function ApplicationDetail() {
  const { sessionId = "" } = useParams();
  const id = cleanSessionId(sessionId);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const application = useQuery({
    queryKey: ["application", id],
    queryFn: () => getApplication(id),
    enabled: Boolean(id),
  });

  const record = application.data?.application ?? null;
  const snapshot = record?.evidence_snapshot ?? record?.local_analysis ?? null;
  const counts = useMemo(() => evidenceCounts(record), [record]);
  const [companyName, setCompanyName] = useState("");
  const [roleTitle, setRoleTitle] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (!record) return;
    setCompanyName(record.company_name);
    setRoleTitle(record.role_title);
    setNotes(record.notes ?? "");
  }, [record]);

  const saveMutation = useMutation({
    mutationFn: () => updateApplication(id, {
      company_name: companyName,
      role_title: roleTitle,
      notes,
    }),
    onSuccess: (response) => {
      qc.setQueryData(["application", id], response);
      void qc.invalidateQueries({ queryKey: ["applications"] });
      toast.success("Application updated.");
    },
    onError: () => toast.error("Update failed."),
  });

  const refreshMutation = useMutation({
    mutationFn: () => refreshApplicationEvidence(id),
    onSuccess: (response) => {
      qc.setQueryData(["application", id], response);
      void qc.invalidateQueries({ queryKey: ["applications"] });
      toast.success("Evidence refreshed.");
    },
    onError: () => toast.error("Evidence refresh failed."),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteApplication(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["applications"] });
      toast.success("Application deleted.");
      navigate("/applications");
    },
    onError: () => toast.error("Delete failed."),
  });

  if (application.isPending) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-12 w-1/3" />
        <Skeleton className="h-80 w-full" />
      </div>
    );
  }

  if (application.isError || !record) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Application not found</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>The saved application either does not exist or is not yours.</p>
          <Link to="/applications" className="underline">
            Back to applications
          </Link>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <Link to="/applications" className="text-sm text-primary underline">
            Back to applications
          </Link>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">
            {record.role_title}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-sm text-foreground/60">{record.company_name}</span>
            <Badge className="border-transparent bg-muted text-muted-foreground">
              {label(record.status)}
            </Badge>
            <Badge className="border-transparent bg-primary/10 text-primary">
              {record.source === "local_jd" ? "Pasted JD" : "Forwarded job"}
            </Badge>
            {record.application_priority && (
              <span className="text-xs font-mono text-primary">
                {label(record.application_priority)}
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            disabled={refreshMutation.isPending}
            onClick={() => refreshMutation.mutate()}
          >
            {refreshMutation.isPending ? "Refreshing..." : "Refresh evidence"}
          </Button>
          <Button
            variant="outline"
            disabled={deleteMutation.isPending}
            onClick={() => {
              if (window.confirm("Delete this saved application?")) {
                deleteMutation.mutate();
              }
            }}
          >
            Delete
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="text-base">Tracker details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label
                htmlFor="application-company"
                className="text-xs font-medium text-muted-foreground"
              >
                Company
              </label>
              <Input
                id="application-company"
                value={companyName}
                onChange={(event) => setCompanyName(event.target.value)}
                className="mt-1"
              />
            </div>
            <div>
              <label
                htmlFor="application-role-title"
                className="text-xs font-medium text-muted-foreground"
              >
                Role title
              </label>
              <Input
                id="application-role-title"
                value={roleTitle}
                onChange={(event) => setRoleTitle(event.target.value)}
                className="mt-1"
              />
            </div>
            <div>
              <label
                htmlFor="application-notes"
                className="text-xs font-medium text-muted-foreground"
              >
                Notes
              </label>
              <Textarea
                id="application-notes"
                rows={5}
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                className="mt-1"
              />
            </div>
            <Button
              className="w-full"
              disabled={saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              {saveMutation.isPending ? "Saving..." : "Save changes"}
            </Button>
            {record.source === "forward_job" && (
              <Link
                to={`/sessions/${record.session_id}`}
                className="block text-center text-sm text-primary underline"
              >
                Open research session
              </Link>
            )}
          </CardContent>
        </Card>

        <div className="space-y-6 lg:col-span-2">
          {snapshot && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Evidence status</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-3 gap-3 text-center">
                  <div className="rounded-md border border-border p-3">
                    <p className="text-xl font-mono text-success">{counts.matched}</p>
                    <p className="text-xs text-muted-foreground">matched</p>
                  </div>
                  <div className="rounded-md border border-border p-3">
                    <p className="text-xl font-mono text-destructive">{counts.missing}</p>
                    <p className="text-xs text-muted-foreground">missing</p>
                  </div>
                  <div className="rounded-md border border-border p-3">
                    <p className="text-xl font-mono text-primary">{counts.confirmation}</p>
                    <p className="text-xs text-muted-foreground">confirm</p>
                  </div>
                </div>
                <div className="space-y-2">
                  {snapshot.evidence_checkpoints.map((item) => (
                    <div
                      key={`${item.requirement}-${item.status}`}
                      className="rounded-md border border-border p-3"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{item.requirement}</span>
                        <Badge className={STATUS_TONE[item.status]}>
                          {label(item.status)}
                        </Badge>
                      </div>
                      <p className="mt-2 text-sm text-muted-foreground">
                        {item.suggested_evidence}
                      </p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {snapshot && (
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Missing evidence</CardTitle>
                </CardHeader>
                <CardContent>
                  {snapshot.missing_evidence_prompts.length ? (
                    <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
                      {snapshot.missing_evidence_prompts.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No missing evidence prompts for the current snapshot.
                    </p>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Unsupported claims</CardTitle>
                </CardHeader>
                <CardContent>
                  {snapshot.unsupported_claim_warnings.length ? (
                    <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
                      {snapshot.unsupported_claim_warnings.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No unsupported-claim warnings for the current snapshot.
                    </p>
                  )}
                </CardContent>
              </Card>
            </div>
          )}

          {snapshot && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Role analysis</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {snapshot.role_breakdown.length > 0 && (
                  <div>
                    <p className="text-xs uppercase tracking-widest text-muted-foreground">
                      Breakdown
                    </p>
                    <ul className="mt-2 space-y-2 text-sm text-muted-foreground">
                      {snapshot.role_breakdown.map((item) => (
                        <li key={item} className="rounded-md border border-border p-3">
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {snapshot.required_skills.length > 0 && (
                  <div>
                    <p className="text-xs uppercase tracking-widest text-muted-foreground">
                      Skills
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {snapshot.required_skills.map((skill) => (
                        <Badge key={skill} className="bg-primary/10 text-primary">
                          {skill}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
                {snapshot.hard_filters.length > 0 && (
                  <div>
                    <p className="text-xs uppercase tracking-widest text-muted-foreground">
                      Hard filters
                    </p>
                    <div className="mt-2 space-y-2">
                      {snapshot.hard_filters.map((filter, index) => (
                        <div
                          key={`${filter.label}-${index}`}
                          className="rounded-md border border-border p-3"
                        >
                          <div className="flex items-center gap-2">
                            <span className="font-medium">{filter.label}</span>
                            <Badge className="bg-muted text-muted-foreground">
                              {filter.severity}
                            </Badge>
                          </div>
                          <p className="mt-2 text-sm text-muted-foreground">
                            {filter.evidence}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {snapshot.answer_strategy.length > 0 && (
                  <div>
                    <p className="text-xs uppercase tracking-widest text-muted-foreground">
                      Answer strategy
                    </p>
                    <ul className="mt-2 list-disc space-y-2 pl-5 text-sm text-muted-foreground">
                      {snapshot.answer_strategy.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {record.raw_jd_text && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Original pasted JD</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="max-h-[480px] overflow-auto whitespace-pre-wrap rounded-md border border-border bg-background/50 p-4 text-sm text-muted-foreground">
                  {record.raw_jd_text}
                </pre>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
