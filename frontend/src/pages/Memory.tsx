import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, Edit3, EyeOff, Lock, RefreshCw, Save, Trash2, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  exportMemory,
  hardDeleteMemoryInboxItem,
  listMemoryInbox,
  purgeExpiredMemoryRaw,
  updateMemoryInboxItem,
} from "@/lib/api";
import type {
  MemoryReviewStatus,
  MemoryVisibility,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type InboxKind = "experience_atom" | "story_frame";

export default function Memory() {
  const queryClient = useQueryClient();
  const inbox = useQuery({
    queryKey: ["memory-inbox", "pending"],
    queryFn: () => listMemoryInbox("pending"),
  });

  const update = useMutation({
    mutationFn: (vars: {
      kind: InboxKind;
      id: string;
      review_status: MemoryReviewStatus;
      visibility?: MemoryVisibility;
      text?: string;
      title?: string;
      summary?: string;
    }) =>
      updateMemoryInboxItem(vars.kind, vars.id, {
        review_status: vars.review_status,
        visibility: vars.visibility,
        text: vars.text,
        title: vars.title,
        summary: vars.summary,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["memory-inbox"] });
      toast.success("Memory updated.");
    },
    onError: () => toast.error("Memory update failed."),
  });

  const hardDelete = useMutation({
    mutationFn: (vars: { kind: InboxKind; id: string }) =>
      hardDeleteMemoryInboxItem(vars.kind, vars.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["memory-inbox"] });
      toast.success("Memory permanently deleted.");
    },
    onError: () => toast.error("Permanent delete failed."),
  });

  const purge = useMutation({
    mutationFn: purgeExpiredMemoryRaw,
    onSuccess: (data) => toast.success(`${data.purged_attempts} expired raw item(s) purged.`),
    onError: () => toast.error("Raw retention purge failed."),
  });

  const downloadExport = useMutation({
    mutationFn: () => exportMemory(true),
    onSuccess: (data) => {
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `askpicky-memory-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);
    },
    onError: () => toast.error("Memory export failed."),
  });

  const atoms = inbox.data?.experience_atoms ?? [];
  const stories = inbox.data?.story_frames ?? [];
  const count = atoms.length + stories.length;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-mono uppercase tracking-[0.3em] text-muted-foreground">
            Profile Memory
          </p>
          <h1 className="font-serif text-4xl">Memory Inbox</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => purge.mutate()}
            disabled={purge.isPending}
          >
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden />
            Purge Expired Raw
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => downloadExport.mutate()}
            disabled={downloadExport.isPending}
          >
            <Download className="mr-2 h-4 w-4" aria-hidden />
            Export
          </Button>
          <Badge variant={count ? "warning" : "secondary"}>{count} pending</Badge>
        </div>
      </header>

      {inbox.isPending ? (
        <div className="rounded-lg border border-canvas bg-secondary/20 p-6 text-sm text-muted-foreground">
          Loading memory.
        </div>
      ) : inbox.isError ? (
        <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-6 text-sm text-destructive">
          Memory inbox unavailable.
        </div>
      ) : count === 0 ? (
        <div className="rounded-lg border border-canvas bg-secondary/20 p-6 text-sm text-muted-foreground">
          No pending memory.
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {atoms.map((atom) => (
            <MemoryCard
              key={atom.atom_id}
              kind="experience_atom"
              id={atom.atom_id}
              title={atom.atom_type.replace("_", " ")}
              body={atom.text}
              source={atom.source_type}
              sensitive={atom.sensitive}
              visibility={atom.visibility}
              onUpdate={(review_status, visibility) =>
                update.mutate({
                  kind: "experience_atom",
                  id: atom.atom_id,
                  review_status,
                  visibility,
                })
              }
              onEdit={(text) =>
                update.mutate({
                  kind: "experience_atom",
                  id: atom.atom_id,
                  review_status: atom.review_status,
                  text,
                })
              }
              onHardDelete={() =>
                hardDelete.mutate({ kind: "experience_atom", id: atom.atom_id })
              }
            />
          ))}
          {stories.map((story) => (
            <MemoryCard
              key={story.story_id}
              kind="story_frame"
              id={story.story_id}
              title={story.title}
              body={story.summary}
              source={story.question_types.join(", ") || "story"}
              sensitive={story.sensitive}
              visibility={story.visibility}
              tags={story.angle_tags}
              onUpdate={(review_status, visibility) =>
                update.mutate({
                  kind: "story_frame",
                  id: story.story_id,
                  review_status,
                  visibility,
                })
              }
              onEdit={(summary, title) =>
                update.mutate({
                  kind: "story_frame",
                  id: story.story_id,
                  review_status: story.review_status,
                  title,
                  summary,
                })
              }
              onHardDelete={() =>
                hardDelete.mutate({ kind: "story_frame", id: story.story_id })
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

function MemoryCard({
  kind,
  id,
  title,
  body,
  source,
  sensitive,
  visibility,
  tags = [],
  onUpdate,
  onEdit,
  onHardDelete,
}: {
  kind: InboxKind;
  id: string;
  title: string;
  body: string;
  source: string;
  sensitive: boolean;
  visibility: MemoryVisibility;
  tags?: string[];
  onUpdate: (status: MemoryReviewStatus, visibility?: MemoryVisibility) => void;
  onEdit: (body: string, title?: string) => void;
  onHardDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState(title);
  const [draftBody, setDraftBody] = useState(body);

  const saveEdit = () => {
    onEdit(draftBody, kind === "story_frame" ? draftTitle : undefined);
    setEditing(false);
  };

  return (
    <Card className="border-canvas bg-card/80">
      <CardHeader className="space-y-3">
        <div className="flex items-start justify-between gap-4">
          <CardTitle className="text-base capitalize">{title}</CardTitle>
          <div className="flex shrink-0 items-center gap-2">
            {visibility === "private" && (
              <Badge variant="warning" className="gap-1">
                <Lock className="h-3 w-3" aria-hidden />
                Private
              </Badge>
            )}
            {sensitive && <Badge variant="destructive">Sensitive</Badge>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2 text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground">
          <span>{kind.replace("_", " ")}</span>
          <span>{source}</span>
          <span>{id.slice(0, 8)}</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {editing ? (
          <div className="space-y-3">
            {kind === "story_frame" && (
              <input
                value={draftTitle}
                onChange={(event) => setDraftTitle(event.target.value)}
                className="w-full rounded-lg border border-canvas bg-background px-3 py-2 text-sm outline-none ring-primary/30 transition focus:ring-2"
              />
            )}
            <textarea
              value={draftBody}
              onChange={(event) => setDraftBody(event.target.value)}
              className="min-h-32 w-full resize-y rounded-lg border border-canvas bg-background px-3 py-2 text-sm outline-none ring-primary/30 transition focus:ring-2"
            />
          </div>
        ) : (
          <p className="text-sm leading-relaxed text-foreground/90">{body}</p>
        )}
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {tags.slice(0, 6).map((tag) => (
              <Badge key={tag} variant="secondary">
                {tag}
              </Badge>
            ))}
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          {editing ? (
            <>
              <Button size="sm" onClick={saveEdit}>
                <Save className="mr-2 h-4 w-4" aria-hidden />
                Save Edit
              </Button>
              <Button size="sm" variant="outline" onClick={() => setEditing(false)}>
                <X className="mr-2 h-4 w-4" aria-hidden />
                Cancel
              </Button>
            </>
          ) : (
            <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
              <Edit3 className="mr-2 h-4 w-4" aria-hidden />
              Edit
            </Button>
          )}
          <Button size="sm" onClick={() => onUpdate("approved")}>
            <Check className="mr-2 h-4 w-4" aria-hidden />
            Approve
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => onUpdate("approved", "private")}
          >
            <Lock className="mr-2 h-4 w-4" aria-hidden />
            Keep Private
          </Button>
          <Button size="sm" variant="outline" onClick={() => onUpdate("hidden")}>
            <EyeOff className="mr-2 h-4 w-4" aria-hidden />
            Hide
          </Button>
          <Button size="sm" variant="destructive" onClick={() => onUpdate("deleted")}>
            <Trash2 className="mr-2 h-4 w-4" aria-hidden />
            Delete
          </Button>
          <Button size="sm" variant="destructive" onClick={onHardDelete}>
            <Trash2 className="mr-2 h-4 w-4" aria-hidden />
            Delete Forever
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
