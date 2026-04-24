import { useReducer } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Sparkles, X } from "lucide-react";

import { ApiError, generatePack } from "@/lib/api";
import { streamFullPrep } from "@/lib/sse";
import type { FullPrepEvent, PackGeneratorName } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

type GenStatus = "idle" | "running" | "complete" | "failed";

interface PerGen {
  status: GenStatus;
  error?: string;
}

type State = Record<PackGeneratorName, PerGen>;

const ALL_GENERATORS: PackGeneratorName[] = [
  "cv",
  "cover_letter",
  "questions",
  "salary",
];

const GENERATOR_LABELS: Record<PackGeneratorName, string> = {
  cv: "CV",
  cover_letter: "Cover letter",
  questions: "Interview questions",
  salary: "Salary strategy",
};

const initial: State = {
  cv: { status: "idle" },
  cover_letter: { status: "idle" },
  questions: { status: "idle" },
  salary: { status: "idle" },
};

type Action =
  | { kind: "individual_started"; generator: PackGeneratorName }
  | { kind: "individual_complete"; generator: PackGeneratorName }
  | { kind: "individual_failed"; generator: PackGeneratorName; error: string }
  | { kind: "full_prep_event"; event: FullPrepEvent };

function reducer(state: State, action: Action): State {
  switch (action.kind) {
    case "individual_started":
      return {
        ...state,
        [action.generator]: { status: "running" },
      };
    case "individual_complete":
      return {
        ...state,
        [action.generator]: { status: "complete" },
      };
    case "individual_failed":
      return {
        ...state,
        [action.generator]: { status: "failed", error: action.error },
      };
    case "full_prep_event": {
      const e = action.event;
      switch (e.type) {
        case "started":
          return {
            ...state,
            [e.generator]: { status: "running" },
          };
        case "completed":
          return {
            ...state,
            [e.generator]: { status: "complete" },
          };
        case "failed":
          return {
            ...state,
            [e.generator]: { status: "failed", error: e.error },
          };
        default:
          return state;
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  sessionId: string;
}

function StatusGlyph({ status }: { status: GenStatus }) {
  switch (status) {
    case "running":
      return (
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />
      );
    case "complete":
      return <Check className="h-4 w-4 text-success" aria-hidden />;
    case "failed":
      return <X className="h-4 w-4 text-destructive" aria-hidden />;
    default:
      return null;
  }
}

export default function PackGenerator({ sessionId }: Props) {
  const [state, dispatch] = useReducer(reducer, initial);
  const queryClient = useQueryClient();

  const anyRunning = ALL_GENERATORS.some(
    (g) => state[g].status === "running",
  );

  const runIndividual = async (generator: PackGeneratorName) => {
    dispatch({ kind: "individual_started", generator });
    try {
      await generatePack(sessionId, generator);
      dispatch({ kind: "individual_complete", generator });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Generation failed.";
      dispatch({ kind: "individual_failed", generator, error: message });
    } finally {
      // Files + cost may have changed — refetch the session detail.
      queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
    }
  };

  const runFullPrep = async () => {
    // Reset all to running so the four columns light up at once;
    // started events from the backend will land milliseconds later.
    for (const g of ALL_GENERATORS) {
      dispatch({ kind: "individual_started", generator: g });
    }
    try {
      await streamFullPrep(sessionId, {
        onEvent: (event) => dispatch({ kind: "full_prep_event", event }),
        onError: (err) => {
          for (const g of ALL_GENERATORS) {
            if (state[g].status !== "complete") {
              dispatch({
                kind: "individual_failed",
                generator: g,
                error: err.message,
              });
            }
          }
        },
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Full prep failed.";
      for (const g of ALL_GENERATORS) {
        dispatch({ kind: "individual_failed", generator: g, error: message });
      }
    } finally {
      queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Generate pack</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {ALL_GENERATORS.map((g) => (
            <div
              key={g}
              className={cn(
                "rounded-md border p-3 transition-colors",
                state[g].status === "complete" && "border-success/50",
                state[g].status === "failed" && "border-destructive/50",
              )}
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="text-sm font-medium">
                  {GENERATOR_LABELS[g]}
                </span>
                <StatusGlyph status={state[g].status} />
              </div>
              <Button
                variant="outline"
                size="sm"
                className="w-full"
                onClick={() => runIndividual(g)}
                disabled={anyRunning}
              >
                {state[g].status === "complete" ? "Regenerate" : "Generate"}
              </Button>
              {state[g].error && (
                <p className="mt-2 text-xs text-destructive">{state[g].error}</p>
              )}
            </div>
          ))}
        </div>
        <div className="flex items-center justify-between gap-3 rounded-md border bg-secondary/30 p-3">
          <div>
            <p className="font-medium">Full prep</p>
            <p className="text-xs text-muted-foreground">
              Runs all four generators in parallel.
            </p>
          </div>
          <Button onClick={runFullPrep} disabled={anyRunning}>
            <Sparkles className="mr-2 h-4 w-4" />
            Run all
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
