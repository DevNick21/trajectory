import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { motion } from "motion/react";
import {
  Briefcase,
  Check,
  PoundSterling,
  Sparkles,
  Mail,
  HelpCircle,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ApiError, generatePack } from "@/lib/api";
import type { GeneratedFile, PackGeneratorName } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const gridVariants = {
  animate: { transition: { staggerChildren: 0.06 } },
} as const;

const cardVariants = {
  initial: { opacity: 0, y: 8, scale: 0.98 },
  animate: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.3 } },
} as const;

interface PackDef {
  generator: PackGeneratorName;
  title: string;
  /** When true, the deep view's preview is the deliverable (CV + cover
   *  letter). When false, the artifact lives entirely in the chat-style
   *  rendered output (salary + questions). Affects nothing today; kept
   *  here so the hub can show "Open file" vs "View" later. */
  hasFile: boolean;
  /** Filename heuristic — if any generated_file matches, the hub
   *  treats this pack as generated. CV + cover letter only; salary +
   *  questions never produce files, so detection falls back to the
   *  react-query cache. */
  filenameMatches?: (filename: string) => boolean;
  Icon: typeof Briefcase;
  routeSegment: string;
}

const PACKS: PackDef[] = [
  {
    generator: "cv",
    title: "Tailored CV",
    hasFile: true,
    filenameMatches: (f) => /_CV_/i.test(f),
    Icon: Briefcase,
    routeSegment: "cv",
  },
  {
    generator: "cover_letter",
    title: "Custom cover letter",
    hasFile: true,
    filenameMatches: (f) => /^CoverLetter_/i.test(f),
    Icon: Mail,
    routeSegment: "cover-letter",
  },
  {
    generator: "salary",
    title: "Salary negotiation strategy",
    hasFile: false,
    Icon: PoundSterling,
    routeSegment: "salary",
  },
  {
    generator: "questions",
    title: "Interview preparation guide",
    hasFile: false,
    Icon: HelpCircle,
    routeSegment: "questions",
  },
];

interface Props {
  sessionId: string;
  files: GeneratedFile[];
}

export default function PackPicker({ sessionId, files }: Props) {
  const queryClient = useQueryClient();
  const [running, setRunning] = useState<Set<PackGeneratorName>>(new Set());
  const [errors, setErrors] = useState<Partial<Record<PackGeneratorName, string>>>({});

  const isGenerated = (pack: PackDef): boolean => {
    if (pack.filenameMatches) {
      if (files.some((f) => pack.filenameMatches!(f.filename))) return true;
    }
    // React-query cache fallback for non-file packs (salary, questions).
    // Set by the DeepWork* containers after successful generation; lives
    // for the SPA session.
    return Boolean(
      queryClient.getQueryData(["pack", sessionId, pack.generator]),
    );
  };

  const regenerate = async (pack: PackDef) => {
    setRunning((prev) => new Set(prev).add(pack.generator));
    setErrors((prev) => ({ ...prev, [pack.generator]: undefined }));
    try {
      const result = await generatePack(sessionId, pack.generator);
      // Park output in the cache so the deep view hydrates on nav.
      queryClient.setQueryData(
        ["pack", sessionId, pack.generator],
        result.output,
      );
      // Files + cost may have changed.
      queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
      // CV may have written new career entries.
      if (pack.generator === "cv") {
        queryClient.invalidateQueries({ queryKey: ["career-entries"] });
      }
      toast.success(`${pack.title} regenerated`);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Generation failed.";
      setErrors((prev) => ({ ...prev, [pack.generator]: message }));
      toast.error(`${pack.title} regenerate failed`, { description: message });
    } finally {
      setRunning((prev) => {
        const next = new Set(prev);
        next.delete(pack.generator);
        return next;
      });
    }
  };

  return (
    <Card className="border-canvas bg-card/50">
      <CardHeader className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-3 sm:space-y-0">
        <div>
          <CardTitle className="font-serif text-2xl">
            Asset Production
          </CardTitle>
          <p className="mt-1 text-sm text-muted-foreground italic">
            "High-precision documents tailored to the target role's DNA."
          </p>
        </div>
        <Badge variant="outline" className="self-start gap-1.5 font-mono text-[10px] uppercase border-primary/20 bg-primary/5 text-primary">
          <Check className="h-3 w-3" aria-hidden />
          System Primed
        </Badge>
      </CardHeader>
      <CardContent>
        <motion.div
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
          variants={gridVariants}
          initial="initial"
          animate="animate"
        >
          {PACKS.map((pack) => (
            <PackCard
              key={pack.generator}
              pack={pack}
              sessionId={sessionId}
              generated={isGenerated(pack)}
              running={running.has(pack.generator)}
              error={errors[pack.generator]}
              onRegenerate={() => regenerate(pack)}
            />
          ))}
        </motion.div>
      </CardContent>
    </Card>
  );
}

function PackCard({
  pack,
  sessionId,
  generated,
  running,
  error,
  onRegenerate,
}: {
  pack: PackDef;
  sessionId: string;
  generated: boolean;
  running: boolean;
  error?: string;
  onRegenerate: () => void;
}) {
  const deepHref = `/sessions/${sessionId}/${pack.routeSegment}`;
  const Icon = pack.Icon;

  return (
    <motion.div
      variants={cardVariants}
      whileHover={{ y: -4 }}
      className={cn(
        "group relative flex flex-col justify-between gap-4 rounded-xl border p-5 transition-all duration-300",
        generated 
          ? "border-success/30 bg-success/5 shadow-lg shadow-success/5" 
          : "border-canvas bg-secondary/20 hover:border-primary/50"
      )}
    >
      <div className="space-y-3">
        <div
          aria-hidden
          className={cn(
            "flex h-12 w-12 items-center justify-center rounded-xl transition-transform group-hover:scale-110 duration-300",
            generated ? "bg-success/20 text-success shadow-lg shadow-success/20" : "bg-background text-muted-foreground border border-canvas",
          )}
        >
          <Icon className="h-5 w-5" />
        </div>
        <div className="space-y-1">
          <p className="font-serif text-lg leading-tight">{pack.title}</p>
          <div className="flex items-center gap-2">
            {generated ? (
              <span className="text-[10px] font-mono text-success uppercase tracking-widest font-bold">● Ready</span>
            ) : (
              <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">○ Awaiting</span>
            )}
          </div>
        </div>
      </div>

      <div className="pt-2">
        {generated ? (
          <div className="flex flex-col gap-2">
            <Link
              to={deepHref}
              className={cn(buttonVariants({ size: "sm", variant: "success" }), "w-full font-bold uppercase tracking-widest text-[10px]")}
            >
              Open File
            </Link>
            <Button
              size="sm"
              variant="ghost"
              className="w-full text-[9px] uppercase tracking-tighter h-7 opacity-50 hover:opacity-100"
              onClick={onRegenerate}
              disabled={running}
            >
              {running ? "Regenerating..." : "Regenerate"}
            </Button>
          </div>
        ) : (
          <Link
            to={deepHref}
            className={cn(buttonVariants({ size: "sm", variant: "default" }), "w-full font-bold uppercase tracking-widest text-[10px]")}
          >
            <Sparkles className="mr-2 h-3 w-3" />
            Generate
          </Link>
        )}
      </div>

      {error && <p className="absolute -bottom-6 left-0 text-[10px] text-destructive truncate w-full">{error}</p>}
    </motion.div>
  );
}
