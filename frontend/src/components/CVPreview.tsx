import { motion } from "motion/react";
import { Loader2, Terminal } from "lucide-react";
import PickyAvatar from "@/components/PickyAvatar";

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
    <Card className="min-h-[28rem] bg-card border-canvas shadow-2xl overflow-hidden relative group">
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary/40 via-success/40 to-primary/40 opacity-0 group-hover:opacity-100 transition-opacity" />
      <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0 border-b border-canvas bg-secondary/30">
        <div className="flex items-center gap-2">
          <Terminal className="h-4 w-4 text-primary" />
          <CardTitle className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Draft Output</CardTitle>
        </div>
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
    <div className="flex min-h-[20rem] flex-col items-center justify-center gap-6 text-center py-12">
      <PickyAvatar state="idle" className="h-20 w-20" />
      <div className="max-w-xs">
        <p className="font-serif text-lg mb-2">"Waiting for my orders."</p>
        <p className="text-xs text-muted-foreground leading-relaxed">
          I'll synthesize your career history into a high-precision document tailored for this JD. Grounded in evidence.
        </p>
      </div>
      <Button 
        onClick={onGenerate}
        className="font-bold uppercase tracking-widest text-[10px] px-8 h-10"
      >
        [ Synthesize CV ]
      </Button>
      {error && (
        <p className="text-xs text-destructive font-mono mt-4" role="alert">
          ERROR: {error}
        </p>
      )}
    </div>
  );
}

function GeneratingState() {
  return (
    <div className="flex min-h-[20rem] flex-col items-center justify-center gap-6 text-center py-12">
      <PickyAvatar state="thinking" className="h-20 w-20" />
      <div className="space-y-2">
        <p className="font-serif text-lg animate-pulse">"Restructuring history..."</p>
        <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">
          Applying writing style profile
        </p>
      </div>
    </div>
  );
}

// CV is fetched in a single POST, but we stagger bullets in to feel
// like the doc is writing itself. The cv prop's `name` keys the outer
// motion.div so a Regenerate replays the cascade.
const documentVariants = {
  initial: { opacity: 0 },
  animate: {
    opacity: 1,
    transition: {
      staggerChildren: 0.18,
      delayChildren: 0.15,
    },
  },
} as const;

const sectionVariants = {
  initial: { opacity: 0, y: 6 },
  animate: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.35, ease: "easeOut" },
  },
} as const;

const roleVariants = {
  animate: {
    transition: { staggerChildren: 0.18 },
  },
} as const;

const bulletListVariants = {
  animate: {
    transition: { staggerChildren: 0.12, delayChildren: 0.1 },
  },
} as const;

const bulletVariants = {
  initial: { opacity: 0, x: -6 },
  animate: {
    opacity: 1,
    x: 0,
    transition: { duration: 0.35, ease: "easeOut" },
  },
} as const;

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
    <motion.article
      key={cv.name + cv.experience.length}
      variants={documentVariants}
      initial="initial"
      animate="animate"
      className="space-y-8 text-card-foreground p-2"
    >
      <motion.header variants={sectionVariants} className="border-b border-canvas pb-6">
        <h2 className="text-3xl font-serif mb-3">{cv.name}</h2>
        {cv.professional_summary && (
          <p className="text-sm leading-relaxed text-muted-foreground italic">
            {cv.professional_summary}
          </p>
        )}
      </motion.header>

      {cv.experience.length > 0 && (
        <motion.section variants={sectionVariants} className="space-y-6">
          <h3 className="text-[10px] font-bold uppercase tracking-[0.2em] text-primary">
            Experience Archive
          </h3>
          <motion.div variants={roleVariants} className="space-y-8">
            {cv.experience.map((role, roleIdx) => (
              <motion.div
                key={roleIdx}
                variants={sectionVariants}
                className="space-y-3"
              >
                <div className="flex items-baseline justify-between gap-3">
                  <p className="font-serif text-lg">
                    {role.title}
                    <span className="text-muted-foreground font-sans text-sm"> · {role.company}</span>
                  </p>
                  <p className="text-[10px] font-mono tabular-nums text-muted-foreground uppercase tracking-widest">
                    {role.dates}
                  </p>
                </div>
                <motion.ul
                  variants={bulletListVariants}
                  className="space-y-1"
                >
                  {role.bullets.map((bullet, bulletIdx) => {
                    const key = `${roleIdx}-${bulletIdx}`;
                    const selected = key === selectedBulletKey;
                    return (
                      <motion.li
                        key={bulletIdx}
                        variants={bulletVariants}
                      >
                        <motion.button
                          type="button"
                          whileHover={{ x: 2 }}
                          transition={{ type: "spring", stiffness: 400, damping: 25 }}
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
                        </motion.button>
                      </motion.li>
                    );
                  })}
                </motion.ul>
              </motion.div>
            ))}
          </motion.div>
        </motion.section>
      )}

      {cv.skills.length > 0 && (
        <motion.section variants={sectionVariants} className="space-y-2">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Skills
          </h3>
          <p className="text-sm">{cv.skills.join(" · ")}</p>
        </motion.section>
      )}

      {cv.education.length > 0 && (
        <motion.section variants={sectionVariants} className="space-y-2">
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
        </motion.section>
      )}
    </motion.article>
  );
}
