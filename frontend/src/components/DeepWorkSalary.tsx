import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError, generatePack } from "@/lib/api";
import type { SalaryRecommendation } from "@/lib/types";
import SalaryPreview from "@/components/SalaryPreview";
import SplitPane, { type ContextBundle } from "@/components/SplitPane";

interface Props {
  sessionId: string;
  bundle: ContextBundle | null;
  initialOutput?: SalaryRecommendation | null;
}

export default function DeepWorkSalary({
  sessionId,
  bundle,
  initialOutput,
}: Props) {
  const [output, setOutput] = useState<SalaryRecommendation | null>(
    initialOutput ?? null,
  );
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const result = await generatePack(sessionId, "salary");
      const sal = result.output as unknown as SalaryRecommendation;
      setOutput(sal);
      queryClient.setQueryData(["pack", sessionId, "salary"], sal);
      queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
      toast.success("Salary strategy ready", {
        description: `Opening £${sal.opening_number.toLocaleString()} (floor £${sal.floor.toLocaleString()}).`,
      });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Salary strategy generation failed.";
      setError(message);
      toast.error("Salary strategy failed", { description: message });
    } finally {
      setGenerating(false);
    }
  };

  return (
    <SplitPane bundle={bundle}>
      <SalaryPreview
        output={output}
        generating={generating}
        error={error}
        onGenerate={handleGenerate}
      />
    </SplitPane>
  );
}
