import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { listApplications, recordOutcome, updateApplicationStatus } from "@/lib/api";
import type {
  ApplicationRecord,
  ApplicationStatus,
  OutcomeKind,
} from "@/lib/types";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const STATUS_COPY: Record<ApplicationStatus, { label: string; tone: string }> = {
  forwarded: { label: "Forwarded", tone: "bg-muted text-muted-foreground" },
  applied: { label: "Applied", tone: "bg-accent text-accent-foreground" },
  no_response: {
    label: "No response",
    tone: "bg-muted text-muted-foreground",
  },
  rejected_screen: { label: "Rejected", tone: "bg-destructive/10 text-destructive" },
  rejected_interview: {
    label: "Rejected (interview)",
    tone: "bg-destructive/10 text-destructive",
  },
  rejected_offer: {
    label: "Rejected (offer)",
    tone: "bg-destructive/10 text-destructive",
  },
  offer_received: {
    label: "Offer",
    tone: "bg-success/10 text-success",
  },
  offer_accepted: {
    label: "Offer accepted",
    tone: "bg-success/15 text-success font-semibold",
  },
  offer_declined: {
    label: "Offer declined",
    tone: "bg-muted text-muted-foreground",
  },
};

const NEXT_ACTIONS: Record<ApplicationStatus, OutcomeKind[]> = {
  forwarded: ["applied", "no_response"],
  applied: ["rejected_screen", "rejected_interview", "offer_received"],
  no_response: ["applied"],
  rejected_screen: [],
  rejected_interview: [],
  rejected_offer: [],
  offer_received: ["offer_accepted", "offer_declined"],
  offer_accepted: [],
  offer_declined: [],
};

const OUTCOME_LABEL: Record<OutcomeKind, string> = {
  applied: "Mark applied",
  no_response: "No response yet",
  rejected_screen: "Rejected",
  rejected_interview: "Rejected at interview",
  rejected_offer: "Rejected the offer",
  offer_received: "Got an offer",
  offer_accepted: "Accepted",
  offer_declined: "Declined",
};

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso.slice(0, 10);
  }
}

function priorityLabel(priority: ApplicationRecord["application_priority"]): string | null {
  if (!priority) return null;
  return priority.replace(/_/g, " ");
}

function ApplicationRow({ record }: { record: ApplicationRecord }) {
  const qc = useQueryClient();
  const mutation = useMutation<unknown, Error, OutcomeKind>({
    mutationFn: (outcome: OutcomeKind) =>
      record.source === "forward_job" && !record.session_id.startsWith("local:")
        ? recordOutcome(record.session_id, outcome)
        : updateApplicationStatus(record.session_id, outcome),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["applications"] });
      qc.invalidateQueries({ queryKey: ["sessions"] });
      toast.success("Updated.");
    },
    onError: () => toast.error("Update failed — try again."),
  });

  const copy = STATUS_COPY[record.status];
  const actions = NEXT_ACTIONS[record.status];
  const snapshot = record.evidence_snapshot ?? record.local_analysis;
  const matchedEvidence = snapshot?.evidence_checkpoints.filter(
    (item) => item.status === "matched",
  ).length ?? 0;
  const missingEvidence = snapshot?.evidence_checkpoints.filter(
    (item) => item.status === "missing" || item.status === "needs_profile",
  ).length ?? 0;
  const needsConfirmation = snapshot?.evidence_checkpoints.filter(
    (item) => item.status === "needs_confirmation",
  ).length ?? 0;
  const linkedTitle = record.source === "forward_job" && !record.session_id.startsWith("local:");
  const titleTarget = linkedTitle
    ? `/sessions/${record.session_id}`
    : `/applications/${encodeURIComponent(record.session_id)}`;
  const priority = priorityLabel(record.application_priority ?? snapshot?.application_priority ?? null);

  return (
    <div className="border-b border-border last:border-b-0 py-3 first:pt-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2 flex-wrap">
            <Link
              to={titleTarget}
              className="font-semibold text-card-foreground hover:text-primary"
            >
              {record.role_title}
            </Link>
            <span className="text-sm text-card-foreground/60">
              · {record.company_name}
            </span>
          </div>
          <div className="mt-1 flex items-center gap-2 flex-wrap">
            <Badge className={copy.tone + " border-transparent"}>
              {copy.label}
            </Badge>
            {record.source === "local_jd" && (
              <Badge className="border-transparent bg-primary/10 text-primary">
                Pasted JD
              </Badge>
            )}
            {record.verdict_decision && (
              <span className="text-xs font-mono text-card-foreground/50">
                Picky: {record.verdict_decision}
              </span>
            )}
            <span className="text-xs text-card-foreground/40">
              · {fmtDate(record.last_status_at)}
            </span>
          </div>
          {(priority || snapshot) && (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-card-foreground/55">
              {priority && (
                <span className="font-mono text-primary">{priority}</span>
              )}
              {snapshot && (
                <>
                  <span>{matchedEvidence} evidence matched</span>
                  <span>{missingEvidence} missing</span>
                  <span>{needsConfirmation} needs confirmation</span>
                </>
              )}
            </div>
          )}
          {snapshot?.missing_evidence_prompts.length ? (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-card-foreground/55">
              {snapshot.missing_evidence_prompts.slice(0, 2).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>
      {actions.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {actions.map((outcome) => (
            <Button
              key={outcome}
              size="sm"
              variant="outline"
              disabled={mutation.isPending}
              onClick={() => mutation.mutate(outcome)}
            >
              {OUTCOME_LABEL[outcome]}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Applications() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["applications"],
    queryFn: () => listApplications({ limit: 200 }),
  });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">
          Applications
        </h1>
        <p className="text-sm text-foreground/60 mt-1">
          Forwarded roles and pasted job descriptions. Update outcomes here.
        </p>
      </header>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">All applications</CardTitle>
        </CardHeader>
        <CardContent>
          {isPending ? (
            <Skeleton className="h-32 w-full" />
          ) : isError ? (
            <p className="text-sm text-destructive">
              Couldn't load applications.
            </p>
          ) : (data?.applications ?? []).length === 0 ? (
            <p className="text-sm text-card-foreground/60">
              Nothing yet. Forward a job URL or paste a job description from
              the dashboard and it will show up here.
            </p>
          ) : (
            <div className="divide-y divide-border">
              {data!.applications.map((r) => (
                <ApplicationRow key={r.id} record={r} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
