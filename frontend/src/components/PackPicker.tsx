import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { motion } from "motion/react";
import {
  Briefcase,
  Check,
  Loader2,
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
  roleTitle: string | null;
  files: GeneratedFile[];
}

export default function PackPicker({ sessionId, roleTitle, files }: Props) {
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
    <Card>
      <CardHeader className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-3 sm:space-y-0">
        <div>
          <CardTitle>
            Choose your application pack
            {roleTitle && (
              <span className="font-normal text-muted-foreground">
                {" "}
                for {roleTitle}
              </span>
            )}
          </CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">
            Based on your profile, job analysis, and tailored questions.
          </p>
        </div>
        {/* Targeted questions status — stub until the workflow lands. */}
        <Badge variant="outline" className="self-start gap-1.5">
          <Check className="h-3.5 w-3.5" aria-hidden />
          Targeted questions answered
        </Badge>
      </CardHeader>
      <CardContent>
        <motion.div
          className="grid gap-3 sm:grid-cols-2"
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

        <p className="mt-6 text-center text-xs text-muted-foreground">
          Need to change your answers?{" "}
          <span className="cursor-not-allowed underline opacity-60">
            Revisit questions
          </span>
        </p>
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
      whileHover={{ y: -2 }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
      className={cn(
        "flex flex-col gap-3 rounded-md border p-4 transition-colors",
        generated && "border-success/40 bg-success/5",
      )}
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-md",
            generated ? "bg-success/10 text-success" : "bg-accent text-accent-foreground",
          )}
        >
          <Icon className="h-4 w-4" />
        </span>
        <div className="flex-1">
          <p className="font-medium">{pack.title}</p>
          <div className="mt-1 flex items-center gap-2 text-xs">
            {generated ? (
              <Badge variant="success" className="gap-1">
                <Check className="h-3 w-3" aria-hidden />
                Generated
              </Badge>
            ) : (
              <span className="text-muted-foreground">Not generated yet</span>
            )}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {generated ? (
          <>
            <Link
              to={deepHref}
              className={buttonVariants({ size: "sm", variant: "outline" })}
            >
              View / edit
            </Link>
            <Button
              size="sm"
              variant="ghost"
              onClick={onRegenerate}
              disabled={running}
            >
              {running ? (
                <>
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                  Regenerating
                </>
              ) : (
                "Regenerate"
              )}
            </Button>
          </>
        ) : (
          <Link
            to={deepHref}
            className={buttonVariants({ size: "sm" })}
          >
            <Sparkles className="mr-2 h-3.5 w-3.5" />
            Generate
          </Link>
        )}
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}
    </motion.div>
  );
}
