import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError, generatePack } from "@/lib/api";
import type { LikelyQuestionsOutput } from "@/lib/types";
import QuestionsPreview from "@/components/QuestionsPreview";
import SplitPane, { type ContextBundle } from "@/components/SplitPane";

interface Props {
  sessionId: string;
  bundle: ContextBundle | null;
  initialOutput?: LikelyQuestionsOutput | null;
}

export default function DeepWorkQuestions({
  sessionId,
  bundle,
  initialOutput,
}: Props) {
  const [output, setOutput] = useState<LikelyQuestionsOutput | null>(
    initialOutput ?? null,
  );
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedQuestionIdx, setSelectedQuestionIdx] =
    useState<number | null>(null);
  const [highlightedEntryIds, setHighlightedEntryIds] = useState<Set<string>>(
    new Set(),
  );
  const [scrollKey, setScrollKey] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const result = await generatePack(sessionId, "questions");
      const out = result.output as unknown as LikelyQuestionsOutput;
      setOutput(out);
      queryClient.setQueryData(["pack", sessionId, "questions"], out);
      queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
      toast.success("Interview prep ready", {
        description: `${out.questions.length} likely questions with strategy notes.`,
      });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Question generation failed.";
      setError(message);
      toast.error("Question generation failed", { description: message });
    } finally {
      setGenerating(false);
    }
  };

  return (
    <SplitPane
      bundle={bundle}
      highlightedEntryIds={highlightedEntryIds}
      scrollKey={scrollKey}
    >
      <QuestionsPreview
        output={output}
        generating={generating}
        error={error}
        selectedQuestionIdx={selectedQuestionIdx}
        onSelectQuestion={(idx, entryIds) => {
          setSelectedQuestionIdx(idx);
          setHighlightedEntryIds(new Set(entryIds));
          setScrollKey(entryIds[0] ?? null);
        }}
        onGenerate={handleGenerate}
      />
    </SplitPane>
  );
}
