import { Loader2, Sparkles } from "lucide-react";

import type {
  LikelyQuestion,
  LikelyQuestionsOutput,
  QuestionBucket,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface Props {
  output: LikelyQuestionsOutput | null;
  generating: boolean;
  error: string | null;
  /** Optional: when a question is hovered/clicked, surface its
   *  relevant_career_entry_ids so the parent can highlight the
   *  matching career history cards. */
  selectedQuestionIdx: number | null;
  onSelectQuestion: (idx: number, entryIds: string[]) => void;
  onGenerate: () => void;
}

const BUCKET_LABEL: Record<QuestionBucket, string> = {
  technical: "Technical",
  experience: "Experience",
  behavioural: "Behavioural",
  motivation_fit: "Motivation fit",
  commercial_strategic: "Commercial",
};

export default function QuestionsPreview({
  output,
  generating,
  error,
  selectedQuestionIdx,
  onSelectQuestion,
  onGenerate,
}: Props) {
  return (
    <Card className="min-h-[28rem]">
      <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0">
        <CardTitle>Interview prep</CardTitle>
        {output && (
          <Button
            variant="outline"
            size="sm"
            onClick={onGenerate}
            disabled={generating}
          >
            {generating ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Regenerating
              </>
            ) : (
              "Regenerate"
            )}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {!output && !generating && (
          <Empty onGenerate={onGenerate} error={error} />
        )}
        {generating && !output && <Generating />}
        {output && (
          <QuestionList
            questions={output.questions}
            selectedQuestionIdx={selectedQuestionIdx}
            onSelectQuestion={onSelectQuestion}
          />
        )}
        {output && error && (
          <p className="mt-4 text-xs text-destructive">{error}</p>
        )}
      </CardContent>
    </Card>
  );
}

function Empty({
  onGenerate,
  error,
}: {
  onGenerate: () => void;
  error: string | null;
}) {
  return (
    <div className="flex min-h-[20rem] flex-col items-center justify-center gap-3 text-center">
      <Sparkles className="h-8 w-8 text-primary" aria-hidden />
      <div>
        <p className="text-sm font-medium">No interview prep yet</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Likely questions, ranked by likelihood, with strategy notes
          tied to your career entries.
        </p>
      </div>
      <Button onClick={onGenerate}>
        <Sparkles className="mr-2 h-4 w-4" />
        Generate questions
      </Button>
      {error && (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function Generating() {
  return (
    <div className="flex min-h-[20rem] flex-col items-center justify-center gap-3 text-center">
      <Loader2 className="h-8 w-8 animate-spin text-primary" aria-hidden />
      <p className="text-sm text-muted-foreground">
        Predicting likely questions…
      </p>
    </div>
  );
}

function QuestionList({
  questions,
  selectedQuestionIdx,
  onSelectQuestion,
}: {
  questions: LikelyQuestion[];
  selectedQuestionIdx: number | null;
  onSelectQuestion: (idx: number, entryIds: string[]) => void;
}) {
  if (questions.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No questions returned by the agent.
      </p>
    );
  }
  return (
    <ul className="space-y-3">
      {questions.map((q, i) => (
        <QuestionCard
          key={i}
          q={q}
          selected={i === selectedQuestionIdx}
          onSelect={() => onSelectQuestion(i, q.relevant_career_entry_ids)}
        />
      ))}
    </ul>
  );
}

function QuestionCard({
  q,
  selected,
  onSelect,
}: {
  q: LikelyQuestion;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        className={cn(
          "w-full rounded-md border p-3 text-left transition-colors",
          selected
            ? "border-primary bg-accent ring-1 ring-primary/40"
            : "hover:bg-muted",
        )}
      >
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <Badge
            variant={q.likelihood === "HIGH" ? "success" : "secondary"}
          >
            {q.likelihood}
          </Badge>
          <Badge variant="outline">{BUCKET_LABEL[q.bucket]}</Badge>
        </div>
        <p className="text-sm font-medium leading-snug">{q.question}</p>
        {q.why_likely && (
          <p className="mt-1 text-xs text-muted-foreground">
            <span className="font-semibold">Why: </span>
            {q.why_likely}
          </p>
        )}
        {q.strategy_note && (
          <p className="mt-2 text-xs leading-relaxed">
            <span className="font-semibold uppercase text-muted-foreground">
              Strategy:{" "}
            </span>
            {q.strategy_note}
          </p>
        )}
      </button>
    </li>
  );
}
