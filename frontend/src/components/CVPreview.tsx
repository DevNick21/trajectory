import { motion } from "motion/react";
import { Loader2, Terminal } from "lucide-react";
import PickyAvatar from "@/components/PickyAvatar";

import type { CVOutput, Citation } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
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
    <Card className="min-h-[28rem] bg-card border-canvas shadow-2xl overflow-hidden relative group flex flex-col">
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary/40 via-success/40 to-primary/40 opacity-0 group-hover:opacity-100 transition-opacity" />
      <div className="absolute inset-0 bg-grid-white/[0.01] bg-[size:30px_30px] pointer-events-none" />
      
      <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0 border-b border-canvas bg-secondary/10 relative z-10 py-3">
        <div className="flex items-center gap-3">
          <div className="p-1.5 rounded bg-background border border-canvas shadow-inner">
            <Terminal className="h-3.5 w-3.5 text-primary" />
          </div>
          <div className="flex flex-col">
            <CardTitle className="text-[10px] font-mono font-bold uppercase tracking-[0.2em] text-muted-foreground leading-none">CV Draft</CardTitle>
            <span className="text-[8px] font-mono text-primary/50 uppercase tracking-widest mt-1">Tailored for Job Description</span>
          </div>
        </div>
        {output && (
          <Button
            variant="outline"
            size="sm"
            onClick={onGenerate}
            disabled={generating}
            className="h-7 text-[9px] font-mono uppercase tracking-widest border-primary/20 hover:border-primary/50 hover:bg-primary/5"
          >
            {generating ? (
              <>
                <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                Regenerating
              </>
            ) : (
              "[ Re-Synthesize ]"
            )}
          </Button>
        )}
      </CardHeader>
      <CardContent className="flex-1 relative z-10 overflow-auto pt-4">
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
          <div className="mt-4 p-3 rounded border border-destructive/20 bg-destructive/5 flex gap-3 items-center">
            <div className="w-1.5 h-1.5 rounded-full bg-destructive animate-pulse" />
            <p className="text-[10px] text-destructive font-mono uppercase tracking-tight">ERROR: {error}</p>
          </div>
        )}
      </CardContent>

      {/* Forensic Footer */}
      <div className="border-t border-canvas bg-secondary/5 px-4 py-2 flex items-center justify-between relative z-10">
        <div className="flex gap-4">
          <div className="flex items-center gap-1.5">
             <div className="w-1 h-1 rounded-full bg-success" />
             <span className="text-[8px] font-mono text-muted-foreground uppercase tracking-widest">Voice: Profile Active</span>
          </div>
          <div className="flex items-center gap-1.5">
             <div className="w-1 h-1 rounded-full bg-success" />
             <span className="text-[8px] font-mono text-muted-foreground uppercase tracking-widest">Grounding: High</span>
          </div>
        </div>
        <span className="text-[8px] font-mono text-muted-foreground/30 uppercase">Trajectory // Lab-ID: {Math.random().toString(36).substring(7).toUpperCase()}</span>
      </div>
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
    <div className="flex min-h-[22rem] flex-col items-center justify-center gap-6 text-center py-12">
      <div className="relative">
        <PickyAvatar state="idle" className="h-24 w-24" />
        <div className="absolute inset-0 blur-2xl bg-primary/10 rounded-full -z-10" />
      </div>
      <div className="max-w-xs space-y-3">
        <p className="font-serif text-xl tracking-tight italic">"Waiting for my orders."</p>
        <p className="text-[11px] text-muted-foreground leading-relaxed font-mono uppercase tracking-tight opacity-70">
          I'll synthesize your career history into a high-precision document tailored for this JD. Grounded in evidence.
        </p>
      </div>
      <Button 
        onClick={onGenerate}
        className="font-bold uppercase tracking-[0.2em] text-[10px] px-10 h-11 bg-primary text-primary-foreground hover:bg-primary/90 shadow-lg shadow-primary/20"
      >
        [ Begin CV Synthesis ]
      </Button>
      {error && (
        <div className="mt-4 p-3 rounded border border-destructive/20 bg-destructive/5 flex gap-3 items-center">
          <div className="w-1.5 h-1.5 rounded-full bg-destructive animate-pulse" />
          <p className="text-[10px] text-destructive font-mono uppercase tracking-tight">System Fault: {error}</p>
        </div>
      )}
    </div>
  );
}

function GeneratingState() {
  return (
    <div className="flex min-h-[22rem] flex-col items-center justify-center gap-8 text-center py-12 relative overflow-hidden">
      <PickyAvatar state="thinking" className="h-24 w-24 z-10" />
      <div className="space-y-4 z-10">
        <div className="flex flex-col items-center gap-1">
          <p className="font-serif text-2xl tracking-tighter italic animate-pulse">"Restructuring history..."</p>
          <div className="w-24 h-0.5 bg-primary/20 relative overflow-hidden rounded-full">
            <div className="absolute top-0 left-0 h-full bg-primary w-1/2 animate-shimmer" />
          </div>
        </div>
        <div className="flex flex-col gap-1">
           <p className="text-[9px] font-mono text-primary uppercase tracking-[0.3em] font-bold">
            Applying writing style profile
          </p>
          <p className="text-[8px] font-mono text-muted-foreground uppercase tracking-widest opacity-50">
            Injecting signature patterns · removing cliches
          </p>
        </div>
      </div>
      
      {/* Background forensic lines */}
      <div className="absolute inset-0 opacity-[0.03] pointer-events-none" 
           style={{ backgroundImage: 'linear-gradient(to bottom, currentColor 1px, transparent 1px)', backgroundSize: '100% 24px' }} />
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
      className="space-y-10 text-card-foreground p-4 bg-background/30 rounded-2xl border border-canvas shadow-inner relative overflow-hidden"
    >
      <div className="absolute top-0 right-0 p-4 opacity-[0.02] pointer-events-none">
        <Terminal className="h-48 w-48 -rotate-12" />
      </div>

      <motion.header variants={sectionVariants} className="border-b-2 border-primary/20 pb-8 relative">
        <div className="flex flex-col gap-1">
          <span className="text-[10px] font-mono text-primary font-bold uppercase tracking-[0.4em]">Professional CV</span>
          <h2 className="text-4xl font-serif font-bold tracking-tight text-foreground">{cv.name}</h2>
        </div>
        {cv.professional_summary && (
          <div className="mt-6 p-4 bg-secondary/20 rounded-xl border border-canvas relative">
             <div className="absolute top-0 left-0 w-1 h-full bg-primary/20" />
             <p className="text-sm leading-relaxed text-muted-foreground italic font-serif">
                {cv.professional_summary}
             </p>
          </div>
        )}
      </motion.header>

      {cv.experience.length > 0 && (
        <motion.section variants={sectionVariants} className="space-y-8">
          <div className="flex items-center gap-4">
             <h3 className="text-[10px] font-mono font-bold uppercase tracking-[0.3em] text-primary whitespace-nowrap">
                Service History
             </h3>
             <div className="h-px bg-canvas flex-1" />
          </div>
          <motion.div variants={roleVariants} className="space-y-10">
            {cv.experience.map((role, roleIdx) => (
              <motion.div
                key={roleIdx}
                variants={sectionVariants}
                className="space-y-4 group/role"
              >
                <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-2 border-b border-canvas/50 pb-2">
                  <div className="flex items-baseline gap-2">
                    <p className="font-serif text-xl font-bold text-foreground">
                      {role.title}
                    </p>
                    <span className="text-muted-foreground font-mono text-xs uppercase tracking-widest"> @ {role.company}</span>
                  </div>
                  <Badge variant="outline" className="text-[10px] font-mono tabular-nums text-muted-foreground uppercase tracking-tighter w-fit">
                    {role.dates}
                  </Badge>
                </div>
                <motion.ul
                  variants={bulletListVariants}
                  className="space-y-2"
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
                          whileHover={{ x: 4 }}
                          transition={{ type: "spring", stiffness: 400, damping: 25 }}
                          onClick={() =>
                            onBulletSelect(key, entryIdsFor(bullet.citations))
                          }
                          className={cn(
                            "flex w-full items-start gap-4 rounded-xl px-4 py-3 text-left text-sm transition-all border group/bullet",
                            selected
                              ? "bg-primary/5 border-primary/30 shadow-sm shadow-primary/5 ring-1 ring-primary/20"
                              : "border-transparent hover:border-canvas hover:bg-secondary/30",
                          )}
                        >
                          <div
                            aria-hidden
                            className={cn(
                              "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full transition-all",
                              selected ? "bg-primary scale-125 shadow-[0_0_8px_rgba(var(--primary),0.6)]" : "bg-muted-foreground/30 group-hover/bullet:bg-primary/50",
                            )}
                          />
                          <span className={cn(
                            "leading-relaxed transition-colors",
                            selected ? "text-foreground font-medium" : "text-muted-foreground group-hover/bullet:text-foreground"
                          )}>{bullet.text}</span>
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

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 pt-6 border-t border-canvas">
        {cv.skills.length > 0 && (
          <motion.section variants={sectionVariants} className="space-y-4">
            <h3 className="text-[10px] font-mono font-bold uppercase tracking-[0.3em] text-primary flex items-center gap-2">
              <div className="w-1 h-1 bg-primary rounded-full" />
              Core Capabilities
            </h3>
            <div className="flex flex-wrap gap-2">
               {cv.skills.map((skill, i) => (
                  <span key={i} className="px-2.5 py-1 bg-background rounded border border-canvas text-[11px] font-mono hover:border-primary/50 transition-colors shadow-sm">{skill}</span>
               ))}
            </div>
          </motion.section>
        )}

        {cv.education.length > 0 && (
          <motion.section variants={sectionVariants} className="space-y-4">
            <h3 className="text-[10px] font-mono font-bold uppercase tracking-[0.3em] text-primary flex items-center gap-2">
              <div className="w-1 h-1 bg-primary rounded-full" />
              Credentials
            </h3>
            <ul className="space-y-3">
              {cv.education.map((edu, i) => (
                <li key={i} className="flex flex-col gap-0.5 p-3 rounded-lg bg-secondary/20 border border-canvas/50">
                  <span className="text-sm font-bold text-foreground">{(edu.degree as string) ?? "Degree"}</span>
                  {edu.institution ? (
                    <span className="text-[11px] font-mono text-muted-foreground uppercase tracking-tight">
                      {edu.institution as string}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </motion.section>
        )}
      </div>
    </motion.article>
  );
}
