import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { ApiError, finaliseOnboarding } from "@/lib/api";
import {
  clearOnboardingDraft,
  useOnboardingDraft,
  validateForFinalise,
} from "@/lib/onboarding";
import { STAGES } from "@/components/onboarding/stages";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// Eight-stage wizard. Persistence is localStorage (ADR-003 — no
// server-side session state). On finalise the draft is cleared and
// the user lands back on /.

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
        `Still missing: ${result.missing.join(", ")}. Go back and fill those in.`,
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
            : "Finalise failed.";
      setSubmitError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const StageComponent = currentStage?.component ?? null;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <ProgressStrip total={totalSteps} active={stepIndex} />

      <Card>
        <CardHeader>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Step {stepIndex + 1} of {totalSteps} ·{" "}
            {isReview ? "Review" : currentStage!.title}
          </p>
        </CardHeader>
        <CardContent>
          {StageComponent ? (
            <StageComponent answers={answers} update={update} />
          ) : (
            <ReviewPanel />
          )}
        </CardContent>
      </Card>

      {submitError && (
        <p className="text-sm text-destructive" role="alert">
          {submitError}
        </p>
      )}

      <div className="flex items-center justify-between">
        <Button
          variant="outline"
          onClick={goBack}
          disabled={stepIndex === 0 || isSubmitting}
        >
          ← Back
        </Button>
        {isReview ? (
          <Button onClick={handleFinalise} disabled={isSubmitting}>
            {isSubmitting ? "Finalising…" : "Finish onboarding"}
          </Button>
        ) : (
          <Button onClick={goNext}>Next →</Button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Progress strip — pills, one per step
// ---------------------------------------------------------------------------

function ProgressStrip({ total, active }: { total: number; active: number }) {
  return (
    <div className="flex gap-1">
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          className={cn(
            "h-1.5 flex-1 rounded-full transition-colors",
            i <= active ? "bg-primary" : "bg-muted",
          )}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Review — last step before submit
// ---------------------------------------------------------------------------

function ReviewPanel() {
  return (
    <div className="space-y-3 text-sm">
      <h2 className="text-lg font-semibold">Ready to go?</h2>
      <p className="text-muted-foreground">
        Finishing writes your profile to the shared store. Both
        Telegram and the web surface read from it after this.
      </p>
      <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
        <li>
          Motivations, deal-breakers, and green flags are parsed
          server-side — plain text is fine.
        </li>
        <li>
          Writing samples feed a one-shot Opus pass that builds your
          style profile. That's what makes generated output sound like
          you, not AI.
        </li>
        <li>
          You can skip back and edit anything before hitting finish.
        </li>
      </ul>
    </div>
  );
}
