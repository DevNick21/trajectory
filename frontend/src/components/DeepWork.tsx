import { useReducer } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError, generatePack } from "@/lib/api";
import type { CVOutput } from "@/lib/types";
import CVPreview from "@/components/CVPreview";
import SplitPane, { type ContextBundle } from "@/components/SplitPane";

interface Props {
  sessionId: string;
  bundle: ContextBundle | null;
  /** Optional: pre-existing CV output (e.g. fetched from a session
   *  cache so the preview is hydrated on direct nav to /sessions/:id/cv).
   *  When omitted, the user must click Generate. */
  initialCV?: CVOutput | null;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

interface State {
  cv: CVOutput | null;
  cvGenerating: boolean;
  cvError: string | null;
  /** "${roleIdx}-${bulletIdx}" of the bullet the user last clicked. */
  selectedBulletKey: string | null;
  /** Entry IDs to ring on the left. Sourced from the selected bullet's
   *  career_entry citations. Empty set when no bullet is selected. */
  highlightedEntryIds: Set<string>;
  /** When highlights change, the first entry id is also a scroll
   *  target so the matching card eases into view. */
  scrollKey: string | null;
}

type Action =
  | { kind: "generate_started" }
  | { kind: "generate_complete"; cv: CVOutput }
  | { kind: "generate_failed"; error: string }
  | { kind: "select_bullet"; bulletKey: string; entryIds: string[] };

function makeInitial(initialCV: CVOutput | null | undefined): State {
  return {
    cv: initialCV ?? null,
    cvGenerating: false,
    cvError: null,
    selectedBulletKey: null,
    highlightedEntryIds: new Set(),
    scrollKey: null,
  };
}

function reducer(state: State, action: Action): State {
  switch (action.kind) {
    case "generate_started":
      return { ...state, cvGenerating: true, cvError: null };
    case "generate_complete":
      return { ...state, cvGenerating: false, cv: action.cv };
    case "generate_failed":
      return { ...state, cvGenerating: false, cvError: action.error };
    case "select_bullet":
      return {
        ...state,
        selectedBulletKey: action.bulletKey,
        highlightedEntryIds: new Set(action.entryIds),
        scrollKey: action.entryIds[0] ?? null,
      };
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DeepWork({ sessionId, bundle, initialCV }: Props) {
  const [state, dispatch] = useReducer(reducer, initialCV, makeInitial);
  const queryClient = useQueryClient();

  const handleGenerate = async () => {
    dispatch({ kind: "generate_started" });
    try {
      const result = await generatePack(sessionId, "cv");
      // PackResult.output is loosely typed at the API edge; cast to
      // CVOutput here since the cv generator's contract is fixed
      // (trajectory.schemas.CVOutput).
      const cv = result.output as unknown as CVOutput;
      dispatch({ kind: "generate_complete", cv });
      // Park output in the SPA's session cache so the hub knows this
      // pack is generated and back-nav rehydrates the preview.
      queryClient.setQueryData(["pack", sessionId, "cv"], cv);
      queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
      // A new CV may have written new cv_bullet career entries.
      queryClient.invalidateQueries({ queryKey: ["career-entries"] });
      toast.success("CV generated", {
        description: "Tailored to the JD using your career history.",
      });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "CV generation failed.";
      dispatch({ kind: "generate_failed", error: message });
      toast.error("CV generation failed", { description: message });
    }
  };

  return (
    <SplitPane
      bundle={bundle}
      highlightedEntryIds={state.highlightedEntryIds}
      scrollKey={state.scrollKey}
    >
      <CVPreview
        output={state.cv}
        generating={state.cvGenerating}
        error={state.cvError}
        selectedBulletKey={state.selectedBulletKey}
        onBulletSelect={(bulletKey, entryIds) =>
          dispatch({ kind: "select_bullet", bulletKey, entryIds })
        }
        onGenerate={handleGenerate}
      />
    </SplitPane>
  );
}
