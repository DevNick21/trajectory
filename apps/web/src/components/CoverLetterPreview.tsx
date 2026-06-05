import { Loader2, Terminal } from "lucide-react";
import PickyAvatar from "@/components/PickyAvatar";

import type { CoverLetterOutput } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Props {
  output: CoverLetterOutput | null;
  generating: boolean;
  error: string | null;
  onGenerate: () => void;
}

export default function CoverLetterPreview({
  output,
  generating,
  error,
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
            <CardTitle className="text-[10px] font-mono font-bold uppercase tracking-[0.2em] text-muted-foreground leading-none">Letter Draft</CardTitle>
            <span className="text-[8px] font-mono text-primary/50 uppercase tracking-widest mt-1">Grounded in Company Research</span>
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
        {output && <Letter cl={output} />}
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
             <span className="text-[8px] font-mono text-muted-foreground uppercase tracking-widest">Culture Grounding: Active</span>
          </div>
          <div className="flex items-center gap-1.5">
             <div className="w-1 h-1 rounded-full bg-success" />
             <span className="text-[8px] font-mono text-muted-foreground uppercase tracking-widest">Style Match: High</span>
          </div>
        </div>
        <span className="text-[8px] font-mono text-muted-foreground/30 uppercase tracking-tighter">REF: CL-{Math.random().toString(36).substring(7).toUpperCase()}</span>
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
          I'll draft a cover letter that cites company research and stays grounded in your approved evidence.
        </p>
      </div>
      <Button 
        onClick={onGenerate}
        className="font-bold uppercase tracking-[0.2em] text-[10px] px-10 h-11 bg-primary text-primary-foreground hover:bg-primary/90 shadow-lg shadow-primary/20"
      >
        [ Synthesize Letter ]
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
          <p className="font-serif text-2xl tracking-tighter italic animate-pulse">"Drafting letter..."</p>
          <div className="w-24 h-0.5 bg-primary/20 relative overflow-hidden rounded-full">
            <div className="absolute top-0 left-0 h-full bg-primary w-1/2 animate-shimmer" />
          </div>
        </div>
        <div className="flex flex-col gap-1">
           <p className="text-[9px] font-mono text-primary uppercase tracking-[0.3em] font-bold">
            Matching company values
          </p>
          <p className="text-[8px] font-mono text-muted-foreground uppercase tracking-widest opacity-50">
            Scanning research bundle · citing engineering blogs
          </p>
        </div>
      </div>
    </div>
  );
}

function Letter({ cl }: { cl: CoverLetterOutput }) {
  return (
    <article className="space-y-8 text-card-foreground p-4 bg-background/30 rounded-2xl border border-canvas shadow-inner relative overflow-hidden">
      <div className="absolute top-0 right-0 p-4 opacity-[0.02] pointer-events-none">
        <Terminal className="h-48 w-48 -rotate-12" />
      </div>

      <header className="border-b-2 border-primary/20 pb-6 relative">
        <div className="flex flex-col gap-1">
          <span className="text-[10px] font-mono text-primary font-bold uppercase tracking-[0.4em]">Recipient</span>
          <p className="font-serif text-2xl font-bold tracking-tight text-foreground">{cl.addressed_to}</p>
        </div>
      </header>
      
      <div className="space-y-6 text-sm leading-relaxed font-serif text-muted-foreground relative">
        {cl.paragraphs.map((p, i) => (
          <p key={i} className="first-letter:text-3xl first-letter:font-bold first-letter:mr-1 first-letter:float-left first-letter:text-foreground first-letter:leading-none">
            {p}
          </p>
        ))}
      </div>
      
      <footer className="border-t border-canvas pt-6 flex justify-between items-center bg-secondary/10 -mx-4 -mb-4 px-4 py-3">
        <div className="flex gap-4">
           <div className="flex items-center gap-2">
              <span className="text-[9px] font-mono text-muted-foreground uppercase tracking-widest">Words:</span>
              <span className="text-[10px] font-mono font-bold text-foreground tabular-nums">{cl.word_count}</span>
           </div>
           <div className="flex items-center gap-2">
              <span className="text-[9px] font-mono text-muted-foreground uppercase tracking-widest">Evidence:</span>
              <span className="text-[10px] font-mono font-bold text-primary tabular-nums">{cl.citations.length} Points</span>
           </div>
        </div>
        <div className="flex items-center gap-2">
           <div className="w-1.5 h-1.5 rounded-full bg-success" />
           <span className="text-[9px] font-mono text-success font-bold uppercase tracking-widest">Verified</span>
        </div>
      </footer>
    </article>
  );
}
