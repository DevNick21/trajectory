import { Loader2, Terminal } from "lucide-react";
import PickyAvatar from "@/components/PickyAvatar";

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
    <Card className="min-h-[28rem] bg-card border-canvas shadow-2xl overflow-hidden relative group">
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary/40 via-success/40 to-primary/40 opacity-0 group-hover:opacity-100 transition-opacity" />
      <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0 border-b border-canvas bg-secondary/30">
        <div className="flex items-center gap-2">
          <Terminal className="h-4 w-4 text-primary" />
          <CardTitle className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Draft Output</CardTitle>
        </div>
        {output && (
          <Button
            variant="outline"
            size="sm"
            onClick={onGenerate}
            disabled={generating}
            className="font-bold uppercase tracking-widest text-[10px]"
          >
            {generating ? (
              <>
                <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                Regenerating
              </>
            ) : (
              "Regenerate"
            )}
          </Button>
        )}
      </CardHeader>
      <CardContent className="pt-6">
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
          <p className="mt-4 text-xs text-destructive font-mono uppercase tracking-widest">ERROR: {error}</p>
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
    <div className="flex min-h-[20rem] flex-col items-center justify-center gap-6 text-center py-12">
      <PickyAvatar state="idle" className="h-20 w-20" />
      <div className="max-w-xs">
        <p className="font-serif text-lg mb-2">"Waiting for my orders."</p>
        <p className="text-xs text-muted-foreground leading-relaxed">
          I'll predict the exact lines of questioning you'll face and tie them to your strongest career evidence.
        </p>
      </div>
      <Button 
        onClick={onGenerate}
        className="font-bold uppercase tracking-widest text-[10px] px-8 h-10"
      >
        [ Predict Questions ]
      </Button>
      {error && (
        <p className="text-xs text-destructive font-mono mt-4" role="alert">
          ERROR: {error}
        </p>
      )}
    </div>
  );
}

function Generating() {
  return (
    <div className="flex min-h-[20rem] flex-col items-center justify-center gap-6 text-center py-12">
      <PickyAvatar state="thinking" className="h-20 w-20" />
      <div className="space-y-2">
        <p className="font-serif text-lg animate-pulse">"Running simulations..."</p>
        <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">
          Analyzing JD requirements against company culture
        </p>
      </div>
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
          "w-full rounded-2xl border border-canvas p-4 text-left transition-all",
          selected
            ? "bg-primary/10 border-primary shadow-lg shadow-primary/5"
            : "hover:bg-secondary/50",
        )}
      >
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Badge
            className={cn(
              "text-[9px] font-mono font-bold uppercase tracking-widest px-2 py-0.5",
              q.likelihood === "HIGH" ? "bg-success/20 text-success border-success/30" : "bg-secondary text-muted-foreground"
            )}
            variant="outline"
          >
            {q.likelihood}
          </Badge>
          <Badge variant="outline" className="text-[9px] font-mono font-bold uppercase tracking-widest px-2 py-0.5 border-canvas">
            {BUCKET_LABEL[q.bucket]}
          </Badge>
        </div>
        <p className="font-serif text-lg leading-snug mb-3">{q.question}</p>
        
        <div className="space-y-3">
          {q.why_likely && (
            <div className="p-2 rounded-lg bg-secondary/30 border border-canvas">
               <p className="text-[10px] leading-relaxed">
                 <span className="font-mono font-bold uppercase tracking-widest text-primary mr-2">Signal:</span>
                 <span className="text-muted-foreground italic">{q.why_likely}</span>
               </p>
            </div>
          )}
          {q.strategy_note && (
            <p className="text-xs leading-relaxed">
              <span className="font-mono font-bold uppercase tracking-widest text-muted-foreground mr-2">Strategy:</span>
              {q.strategy_note}
            </p>
          )}
        </div>
      </button>
    </li>
  );
}
