import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError, generatePack } from "@/lib/api";
import type { CoverLetterOutput } from "@/lib/types";
import CoverLetterPreview from "@/components/CoverLetterPreview";
import SplitPane, { type ContextBundle } from "@/components/SplitPane";

interface Props {
  sessionId: string;
  bundle: ContextBundle | null;
  initialOutput?: CoverLetterOutput | null;
}

export default function DeepWorkCoverLetter({
  sessionId,
  bundle,
  initialOutput,
}: Props) {
  const [output, setOutput] = useState<CoverLetterOutput | null>(
    initialOutput ?? null,
  );
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const result = await generatePack(sessionId, "cover_letter");
      const cl = result.output as unknown as CoverLetterOutput;
      setOutput(cl);
      queryClient.setQueryData(["pack", sessionId, "cover_letter"], cl);
      queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
      toast.success("Cover letter drafted", {
        description: `${cl.word_count} words · ${cl.citations.length} citations.`,
      });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Cover letter generation failed.";
      setError(message);
      toast.error("Cover letter generation failed", { description: message });
    } finally {
      setGenerating(false);
    }
  };

  return (
    <SplitPane bundle={bundle}>
      <CoverLetterPreview
        output={output}
        generating={generating}
        error={error}
        onGenerate={handleGenerate}
      />
    </SplitPane>
  );
}
