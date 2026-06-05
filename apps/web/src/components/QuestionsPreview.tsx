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
    <Card className="min-h-[28rem] bg-card border-canvas shadow-2xl overflow-hidden relative group flex flex-col">
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary/40 via-success/40 to-primary/40 opacity-0 group-hover:opacity-100 transition-opacity" />
      <div className="absolute inset-0 bg-grid-white/[0.01] bg-[size:30px_30px] pointer-events-none" />

      <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0 border-b border-canvas bg-secondary/10 relative z-10 py-3">
        <div className="flex items-center gap-3">
          <div className="p-1.5 rounded bg-background border border-canvas shadow-inner">
            <Terminal className="h-3.5 w-3.5 text-primary" />
          </div>
          <div className="flex flex-col">
            <CardTitle className="text-[10px] font-mono font-bold uppercase tracking-[0.2em] text-muted-foreground leading-none">Interview Prep</CardTitle>
            <span className="text-[8px] font-mono text-primary/50 uppercase tracking-widest mt-1">Predicted Questions & Strategy</span>
          </div>
        </div>
        {output && (
          <Button
            variant="outline"
            size="sm"
            onClick={onGenerate}
            disabled={generating}
            className="h-7 text-[9px] font-mono uppercase tracking-widest border-primary/20 hover:border-primary/50 hover:bg-primary/5"
          >
            {generating ? (
              <>
                <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                Regenerating
              </>
            ) : (
              "[ Re-Synthesize ]"
            )}
          </Button>
        )}
      </CardHeader>
      <CardContent className="flex-1 relative z-10 overflow-auto pt-4">
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
          <div className="mt-4 p-3 rounded border border-destructive/20 bg-destructive/5 flex gap-3 items-center">
            <div className="w-1.5 h-1.5 rounded-full bg-destructive animate-pulse" />
            <p className="text-[10px] text-destructive font-mono uppercase tracking-tight">ERROR: {error}</p>
          </div>
        )}
      </CardContent>

      {/* Forensic Footer */}
      <div className="border-t border-canvas bg-secondary/5 px-4 py-2 flex items-center justify-between relative z-10">
        <div className="flex gap-4">
          <div className="flex items-center gap-1.5">
             <div className="w-1 h-1 rounded-full bg-success" />
             <span className="text-[8px] font-mono text-muted-foreground uppercase tracking-widest">Simulations: High Fidelity</span>
          </div>
          <div className="flex items-center gap-1.5">
             <div className="w-1 h-1 rounded-full bg-success" />
             <span className="text-[8px] font-mono text-muted-foreground uppercase tracking-widest">JD Correlation: OK</span>
          </div>
        </div>
        <span className="text-[8px] font-mono text-muted-foreground/30 uppercase tracking-tighter">SIM-ID: {Math.random().toString(36).substring(7).toUpperCase()}</span>
      </div>
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
    <div className="flex min-h-[22rem] flex-col items-center justify-center gap-6 text-center py-12">
      <div className="relative">
        <PickyAvatar state="idle" className="h-24 w-24" />
        <div className="absolute inset-0 blur-2xl bg-primary/10 rounded-full -z-10" />
      </div>
      <div className="max-w-xs space-y-3">
        <p className="font-serif text-xl tracking-tight italic">"Waiting for my orders."</p>
        <p className="text-[11px] text-muted-foreground leading-relaxed font-mono uppercase tracking-tight opacity-70">
          I'll predict the exact lines of questioning you'll face and tie them to your strongest career evidence.
        </p>
      </div>
      <Button 
        onClick={onGenerate}
        className="font-bold uppercase tracking-[0.2em] text-[10px] px-10 h-11 bg-primary text-primary-foreground hover:bg-primary/90 shadow-lg shadow-primary/20"
      >
        [ Predict Questions ]
      </Button>
      {error && (
        <div className="mt-4 p-3 rounded border border-destructive/20 bg-destructive/5 flex gap-3 items-center">
          <div className="w-1.5 h-1.5 rounded-full bg-destructive animate-pulse" />
          <p className="text-[10px] text-destructive font-mono uppercase tracking-tight">System Fault: {error}</p>
        </div>
      )}
    </div>
  );
}

function Generating() {
  return (
    <div className="flex min-h-[22rem] flex-col items-center justify-center gap-8 text-center py-12 relative overflow-hidden">
      <PickyAvatar state="thinking" className="h-24 w-24 z-10" />
      <div className="space-y-4 z-10">
        <div className="flex flex-col items-center gap-1">
          <p className="font-serif text-2xl tracking-tighter italic animate-pulse">"Running simulations..."</p>
          <div className="w-24 h-0.5 bg-primary/20 relative overflow-hidden rounded-full">
            <div className="absolute top-0 left-0 h-full bg-primary w-1/2 animate-shimmer" />
          </div>
        </div>
        <div className="flex flex-col gap-1">
           <p className="text-[9px] font-mono text-primary uppercase tracking-[0.3em] font-bold">
            Predicting Interview Questions
          </p>
          <p className="text-[8px] font-mono text-muted-foreground uppercase tracking-widest opacity-50">
            Analyzing JD requirements against company culture
          </p>
        </div>
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
      <div className="flex flex-col items-center justify-center py-12 text-center space-y-2 opacity-50">
        <Terminal className="h-8 w-8 text-muted-foreground mb-2" />
        <p className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground">
          Zero simulation output.
        </p>
      </div>
    );
  }
  return (
    <ul className="space-y-4 p-2">
      {questions.map((q, i) => (
        <QuestionCard
          key={i}
          q={q}
          index={i}
          selected={i === selectedQuestionIdx}
          onSelect={() => onSelectQuestion(i, q.relevant_career_entry_ids)}
        />
      ))}
    </ul>
  );
}

function QuestionCard({
  q,
  index,
  selected,
  onSelect,
}: {
  q: LikelyQuestion;
  index: number;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <li className="relative group/q">
      <button
        type="button"
        onClick={onSelect}
        className={cn(
          "w-full rounded-2xl border p-5 text-left transition-all relative overflow-hidden",
          selected
            ? "bg-primary/5 border-primary shadow-lg shadow-primary/5 ring-1 ring-primary/20"
            : "border-canvas bg-background/50 hover:bg-secondary/30",
        )}
      >
        <div className="absolute top-0 left-0 w-1 h-full bg-primary/20 transition-colors group-hover/q:bg-primary/40" />
        
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
           <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono font-bold text-primary/40 mr-2">{String(index + 1).padStart(2, '0')}</span>
              <Badge
                className={cn(
                  "text-[9px] font-mono font-bold uppercase tracking-widest px-2 py-0.5",
                  q.likelihood === "HIGH" ? "bg-success/10 text-success border-success/30" : "bg-secondary text-muted-foreground"
                )}
                variant="outline"
              >
                {q.likelihood} Probability
              </Badge>
           </div>
          <Badge variant="outline" className="text-[9px] font-mono font-bold uppercase tracking-widest px-2 py-0.5 border-canvas/50 bg-background/50">
            {BUCKET_LABEL[q.bucket]}
          </Badge>
        </div>
        
        <p className="font-serif text-xl font-bold tracking-tight leading-tight mb-4 text-foreground">{q.question}</p>
        
        <div className="space-y-3">
          {q.why_likely && (
            <div className="p-3 rounded-xl bg-secondary/30 border border-canvas relative overflow-hidden group/evidence">
               <div className="absolute inset-0 bg-grid-white/[0.02] bg-[size:10px_10px]" />
               <p className="text-[11px] leading-relaxed relative z-10 flex gap-2">
                 <span className="font-mono font-bold uppercase tracking-[0.2em] text-primary/70 shrink-0">Signal:</span>
                 <span className="text-muted-foreground italic font-mono uppercase tracking-tight opacity-80">{q.why_likely}</span>
               </p>
            </div>
          )}
          {q.strategy_note && (
            <div className="flex gap-2">
              <span className="font-mono font-bold uppercase tracking-[0.2em] text-[10px] text-muted-foreground shrink-0 mt-0.5">Strategy:</span>
              <p className="text-sm leading-relaxed text-foreground font-medium italic">
                {q.strategy_note}
              </p>
            </div>
          )}
        </div>
        
        {selected && (
           <div className="mt-4 pt-4 border-t border-primary/20 flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
              <span className="text-[9px] font-mono text-primary font-bold uppercase tracking-widest">Linked career evidence active</span>
           </div>
        )}
      </button>
    </li>
  );
}
