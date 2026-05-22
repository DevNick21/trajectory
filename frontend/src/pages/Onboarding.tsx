import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "motion/react";
import PickyAvatar from "@/components/PickyAvatar";

import { ApiError, finaliseOnboarding } from "@/lib/api";
import {
  clearOnboardingDraft,
  useOnboardingDraft,
  validateForFinalise,
} from "@/lib/onboarding";
import { STAGES } from "@/components/onboarding/stages";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const PICKY_COMMENTS = [
  "Let's start with the basics. Any old CV will do.",
  "Your name and current coordinates. Just so I know who I'm working for.",
  "The Bureaucracy. If you need a sponsor, I'll check every company's register entry.",
  "Let's talk numbers. I'll compare these against ASHE market percentiles.",
  "How urgent is this? I need to know how hard to push on salary.",
  "What actually gets you out of bed? I'll score roles against these.",
  "What makes you walk away? I'll flag these as HARD BLOCKERS.",
  "The Narrative. Tell it your way—I'll use it to ground my drafts.",
  "Your Voice. Paste samples so I don't sound like a generic bot.",
  "Final Review. Scrutinize everything before I commit it to the archive."
];

export default function Onboarding() {
  const { answers, update, reset } = useOnboardingDraft();
  const [stepIndex, setStepIndex] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const totalSteps = STAGES.length + 1; // +1 for the review step
  const isReview = stepIndex === STAGES.length;
  const currentStage = !isReview ? STAGES[stepIndex] : null;

  const goBack = () => setStepIndex((i) => Math.max(0, i - 1));
  const goNext = () => setStepIndex((i) => Math.min(totalSteps - 1, i + 1));

  const handleFinalise = async () => {
    setSubmitError(null);
    const result = validateForFinalise(answers);
    if (!result.ok) {
      setSubmitError(
        `Missing critical parameters: ${result.missing.join(", ")}.`,
      );
      return;
    }
    setIsSubmitting(true);
    try {
      await finaliseOnboarding(result.payload);
      clearOnboardingDraft();
      reset();
      await queryClient.invalidateQueries({ queryKey: ["profile"] });
      navigate("/");
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Calibration failed.";
      setSubmitError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const StageComponent = currentStage?.component ?? null;

  return (
    <div className="max-w-4xl mx-auto px-4 py-12">
      <div className="flex flex-col items-center mb-12 text-center">
        <PickyAvatar state={isSubmitting ? "thinking" : "idle"} className="h-24 w-24 mb-6" />
        <h1 className="font-serif text-3xl mb-2">Picky Calibration</h1>
        <p className="text-muted-foreground font-mono text-xs uppercase tracking-widest">
          Step {stepIndex + 1} of {totalSteps} — {isReview ? "Final Review" : currentStage?.title}
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-12 gap-12 items-start">
        <div className="md:col-span-4 space-y-6 hidden md:block">
          <Card className="bg-secondary/30 border-canvas overflow-hidden">
            <div className="h-1 bg-primary/20 w-full overflow-hidden">
              <motion.div 
                className="h-full bg-primary"
                initial={{ width: "0%" }}
                animate={{ width: `${((stepIndex + 1) / totalSteps) * 100}%` }}
              />
            </div>
            <CardContent className="p-6">
              <p className="font-serif italic text-lg leading-relaxed mb-4">
                "{PICKY_COMMENTS[stepIndex]}"
              </p>
              <div className="pt-4 border-t border-canvas space-y-4">
                 {STAGES.map((s, i) => (
                   <div key={s.key} className={cn(
                     "flex items-center gap-3 text-[10px] font-mono uppercase tracking-widest transition-opacity",
                     i === stepIndex ? "opacity-100 text-primary" : i < stepIndex ? "opacity-40" : "opacity-20"
                   )}>
                     <div className={cn("h-1.5 w-1.5 rounded-full", i <= stepIndex ? "bg-primary" : "bg-muted")} />
                     {s.title}
                   </div>
                 ))}
                 <div className={cn(
                   "flex items-center gap-3 text-[10px] font-mono uppercase tracking-widest transition-opacity",
                   isReview ? "opacity-100 text-primary" : "opacity-20"
                 )}>
                   <div className={cn("h-1.5 w-1.5 rounded-full", isReview ? "bg-primary" : "bg-muted")} />
                   Review
                 </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="md:col-span-8 space-y-8">
          <AnimatePresence mode="wait">
            <motion.div
              key={stepIndex}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.3 }}
            >
              <Card className="shadow-2xl shadow-primary/5 border-canvas">
                <CardContent className="p-8">
                  {StageComponent ? (
                    <StageComponent answers={answers} update={update} />
                  ) : (
                    <ReviewPanel />
                  )}
                </CardContent>
              </Card>
            </motion.div>
          </AnimatePresence>

          {submitError && (
            <motion.div 
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="p-4 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm font-mono"
            >
              <span className="font-bold mr-2">CALIBRATION ERROR:</span>
              {submitError}
            </motion.div>
          )}

          <div className="flex items-center justify-between pt-4">
            <Button
              variant="ghost"
              className="font-mono text-xs uppercase tracking-widest"
              onClick={goBack}
              disabled={stepIndex === 0 || isSubmitting}
            >
              [ Previous ]
            </Button>
            
            {isReview ? (
              <Button 
                onClick={handleFinalise} 
                disabled={isSubmitting}
                className="font-bold uppercase tracking-[0.2em] px-8 h-12"
              >
                {isSubmitting ? "Processing..." : "Commit Profile"}
              </Button>
            ) : (
              <Button 
                onClick={goNext}
                className="font-bold uppercase tracking-[0.2em] px-8 h-12"
              >
                Continue →
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Review — last step before submit
// ---------------------------------------------------------------------------

function ReviewPanel() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h2 className="text-2xl font-serif">Confirm Archive Details</h2>
        <p className="text-muted-foreground text-sm">
          Committing this profile will calibrate my search filters and writing generators. You can always re-calibrate later.
        </p>
      </div>
      
      <div className="grid grid-cols-1 gap-4 font-mono text-[10px] uppercase tracking-widest opacity-60">
        <div className="p-4 rounded-xl border border-canvas flex justify-between">
          <span>Sponsor Register Audit</span>
          <span className="text-success">READY</span>
        </div>
        <div className="p-4 rounded-xl border border-canvas flex justify-between">
          <span>Salary Percentile Link</span>
          <span className="text-success">READY</span>
        </div>
        <div className="p-4 rounded-xl border border-canvas flex justify-between">
          <span>Voice Style Profiler</span>
          <span className="text-success">READY</span>
        </div>
      </div>

      <div className="p-4 rounded-xl bg-secondary/30 border border-canvas italic text-sm text-muted-foreground">
        "I'm ready when you are. Just hit that button and let's get to work. There are a lot of bad jobs out there, and someone needs to find them before you do."
      </div>
    </div>
  );
}
