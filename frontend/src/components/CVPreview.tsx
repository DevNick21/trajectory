import { Loader2, Sparkles } from "lucide-react";

import type { CVOutput, Citation } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface Props {
  /** Generated CV — null until the user clicks Generate. */
  output: CVOutput | null;
  /** True while the generate POST is in flight. */
  generating: boolean;
  /** Last error from the generate call, if any. */
  error: string | null;
  /** Stable key of the currently-selected bullet, e.g. "0-3". */
  selectedBulletKey: string | null;
  /** Click handler — receives the bullet's career_entry citation IDs
   *  (deduped) so the parent can highlight the matching cards on the
   *  left. Empty array means "this bullet has no career_entry citations
   *  to highlight" — in which case the parent should still update the
   *  selection state to clear any prior highlight. */
  onBulletSelect: (bulletKey: string, entryIds: string[]) => void;
  /** Generate button click. */
  onGenerate: () => void;
}

function entryIdsFor(citations: Citation[]): string[] {
  const ids = new Set<string>();
  for (const c of citations) {
    if (c.kind === "career_entry" && c.entry_id) ids.add(c.entry_id);
  }
  return Array.from(ids);
}

export default function CVPreview({
  output,
  generating,
  error,
  selectedBulletKey,
  onBulletSelect,
  onGenerate,
}: Props) {
  return (
    <Card className="min-h-[28rem]">
      <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0">
        <CardTitle>Generated CV</CardTitle>
        {output && (
          <Button
            variant="outline"
            size="sm"
            onClick={onGenerate}
            disabled={generating}
          >
            {generating ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Regenerating
              </>
            ) : (
              "Regenerate"
            )}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {!output && !generating && (
          <EmptyState onGenerate={onGenerate} error={error} />
        )}
        {generating && !output && <GeneratingState />}
        {output && (
          <CVDocument
            cv={output}
            selectedBulletKey={selectedBulletKey}
            onBulletSelect={onBulletSelect}
          />
        )}
        {output && error && (
          <p className="mt-4 text-xs text-destructive">{error}</p>
        )}
      </CardContent>
    </Card>
  );
}

function EmptyState({
  onGenerate,
  error,
}: {
  onGenerate: () => void;
  error: string | null;
}) {
  return (
    <div className="flex min-h-[20rem] flex-col items-center justify-center gap-3 text-center">
      <Sparkles className="h-8 w-8 text-primary" aria-hidden />
      <div>
        <p className="text-sm font-medium">No CV generated yet</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Tailor a CV against this role&rsquo;s JD using your career
          history. Each bullet is grounded — click one to see the
          source on the left.
        </p>
      </div>
      <Button onClick={onGenerate}>
        <Sparkles className="mr-2 h-4 w-4" />
        Generate CV
      </Button>
      {error && (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function GeneratingState() {
  return (
    <div className="flex min-h-[20rem] flex-col items-center justify-center gap-3 text-center">
      <Loader2 className="h-8 w-8 animate-spin text-primary" aria-hidden />
      <p className="text-sm text-muted-foreground">
        Tailoring your CV…
      </p>
    </div>
  );
}

function CVDocument({
  cv,
  selectedBulletKey,
  onBulletSelect,
}: {
  cv: CVOutput;
  selectedBulletKey: string | null;
  onBulletSelect: (bulletKey: string, entryIds: string[]) => void;
}) {
  return (
    <article className="space-y-6 text-card-foreground">
      <header className="border-b pb-4">
        <h2 className="text-xl font-bold">{cv.name}</h2>
        {cv.professional_summary && (
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            {cv.professional_summary}
          </p>
        )}
      </header>

      {cv.experience.length > 0 && (
        <section className="space-y-4">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Experience
          </h3>
          {cv.experience.map((role, roleIdx) => (
            <div key={roleIdx} className="space-y-2">
              <div className="flex items-baseline justify-between gap-3">
                <p className="font-medium">
                  {role.title}
                  <span className="text-muted-foreground"> · {role.company}</span>
                </p>
                <p className="text-xs tabular-nums text-muted-foreground">
                  {role.dates}
                </p>
              </div>
              <ul className="space-y-1">
                {role.bullets.map((bullet, bulletIdx) => {
                  const key = `${roleIdx}-${bulletIdx}`;
                  const selected = key === selectedBulletKey;
                  return (
                    <li key={bulletIdx}>
                      <button
                        type="button"
                        onClick={() =>
                          onBulletSelect(key, entryIdsFor(bullet.citations))
                        }
                        className={cn(
                          "flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                          selected
                            ? "bg-accent text-accent-foreground ring-1 ring-primary/40"
                            : "hover:bg-muted",
                        )}
                      >
                        <span
                          aria-hidden
                          className={cn(
                            "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                            selected ? "bg-primary" : "bg-muted-foreground/40",
                          )}
                        />
                        <span className="leading-snug">{bullet.text}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </section>
      )}

      {cv.skills.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Skills
          </h3>
          <p className="text-sm">{cv.skills.join(" · ")}</p>
        </section>
      )}

      {cv.education.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Education
          </h3>
          <ul className="space-y-1 text-sm">
            {cv.education.map((edu, i) => (
              <li key={i}>
                {(edu.degree as string) ?? "Degree"}
                {edu.institution ? (
                  <span className="text-muted-foreground">
                    {" "}
                    · {edu.institution as string}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
