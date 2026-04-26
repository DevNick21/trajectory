import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { Briefcase, FileText, Quote, Sparkles } from "lucide-react";

import { listCareerEntries } from "@/lib/api";
import type { CareerEntry, CareerEntryKind } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

// Kinds that read as "career history" — what the left pane primarily
// surfaces. Other kinds (motivation, deal_breaker, writing_sample, etc.)
// can still appear *if* a CV bullet cites one of them, but we don't
// list those by default.
const PRIMARY_KINDS: CareerEntryKind[] = [
  "cv_bullet",
  "conversation",
  "project_note",
  "star_polish",
  "qa_answer",
];

const KIND_LABEL: Record<CareerEntryKind, string> = {
  cv_bullet: "CV bullet",
  conversation: "Career narrative",
  project_note: "Project note",
  star_polish: "STAR story",
  qa_answer: "Q&A answer",
  preference: "Preference",
  motivation: "Motivation",
  deal_breaker: "Deal-breaker",
  good_role_signal: "Green flag",
  writing_sample: "Writing sample",
};

const KIND_ICON: Record<CareerEntryKind, typeof Briefcase> = {
  cv_bullet: Briefcase,
  conversation: Quote,
  project_note: FileText,
  star_polish: Sparkles,
  qa_answer: FileText,
  preference: FileText,
  motivation: FileText,
  deal_breaker: FileText,
  good_role_signal: FileText,
  writing_sample: Quote,
};

interface Props {
  /** entry_ids the user just clicked a bullet citing. Cards in this
   *  set get a violet ring and scroll into view. */
  highlightedEntryIds: Set<string>;
  /** Optional: id of the entry to scroll to when highlights change.
   *  When the highlight set is non-empty, the first matching card
   *  scrolls itself into view. */
  scrollKey?: string | null;
}

export default function CareerHistory({
  highlightedEntryIds,
  scrollKey,
}: Props) {
  const q = useQuery({
    queryKey: ["career-entries"],
    queryFn: () => listCareerEntries(),
    retry: false,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">My career history</CardTitle>
      </CardHeader>
      <CardContent>
        {q.isPending ? (
          <div className="space-y-2">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : q.isError ? (
          <p className="text-sm text-destructive">
            Couldn&rsquo;t load career entries.
          </p>
        ) : (
          <CareerList
            entries={q.data?.entries ?? []}
            highlightedEntryIds={highlightedEntryIds}
            scrollKey={scrollKey ?? null}
          />
        )}
      </CardContent>
    </Card>
  );
}

const listVariants = {
  animate: { transition: { staggerChildren: 0.04 } },
} as const;

const itemVariants = {
  initial: { opacity: 0, y: 4 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.25 } },
} as const;

function CareerList({
  entries,
  highlightedEntryIds,
  scrollKey,
}: {
  entries: CareerEntry[];
  highlightedEntryIds: Set<string>;
  scrollKey: string | null;
}) {
  // Show primary-kind entries by default; collapse the rest under a
  // disclosure. When the cited entry happens to be a non-primary kind
  // (e.g. the CV cited a motivation), force-include it in the visible
  // list so the highlight has somewhere to land.
  const forcedVisibleIds = highlightedEntryIds;
  const primary = entries.filter(
    (e) =>
      PRIMARY_KINDS.includes(e.kind) || forcedVisibleIds.has(e.entry_id),
  );

  if (primary.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No career entries yet. Onboarding writes career-narrative + CV
        bullets into this list as you generate packs.
      </p>
    );
  }

  return (
    <motion.ul
      className="space-y-2"
      variants={listVariants}
      initial="initial"
      animate="animate"
    >
      {primary.map((e) => (
        <EntryCard
          key={e.entry_id}
          entry={e}
          highlighted={highlightedEntryIds.has(e.entry_id)}
          shouldScroll={scrollKey === e.entry_id}
        />
      ))}
    </motion.ul>
  );
}

function EntryCard({
  entry,
  highlighted,
  shouldScroll,
}: {
  entry: CareerEntry;
  highlighted: boolean;
  shouldScroll: boolean;
}) {
  const Icon = KIND_ICON[entry.kind] ?? FileText;
  const ref = useRef<HTMLLIElement>(null);

  // Smooth-scroll into view when this entry becomes the citation target.
  // Tracks `shouldScroll` flips so the same entry can be re-targeted by
  // re-clicking a bullet (the parent reducer already mints a fresh
  // scrollKey on every select_bullet action).
  useEffect(() => {
    if (shouldScroll && ref.current) {
      ref.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [shouldScroll]);

  return (
    <motion.li
      ref={ref}
      variants={itemVariants}
      layout
      data-entry-id={entry.entry_id}
      animate={{
        boxShadow: highlighted
          ? "0 0 0 3px hsl(var(--ring) / 0.5)"
          : "0 0 0 0px hsl(var(--ring) / 0)",
        backgroundColor: highlighted
          ? "hsl(var(--accent))"
          : "hsl(var(--card))",
      }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className={cn(
        "rounded-md border p-3 text-sm",
        highlighted ? "border-primary" : "border-border",
      )}
    >
      <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
        <Icon className="h-3.5 w-3.5" aria-hidden />
        {KIND_LABEL[entry.kind] ?? entry.kind}
      </div>
      <p className="line-clamp-3 leading-snug">{entry.raw_text}</p>
    </motion.li>
  );
}
