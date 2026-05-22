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
        {output && <Letter cl={output} />}
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
          I'll draft a cover letter that cites company research and matches your unique writing style profile.
        </p>
      </div>
      <Button 
        onClick={onGenerate}
        className="font-bold uppercase tracking-widest text-[10px] px-8 h-10"
      >
        [ Synthesize Letter ]
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
        <p className="font-serif text-lg animate-pulse">"Drafting manifesto..."</p>
        <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">
          Correlating career entries with company values
        </p>
      </div>
    </div>
  );
}

function Letter({ cl }: { cl: CoverLetterOutput }) {
  return (
    <article className="space-y-6 text-card-foreground">
      <header className="border-b border-canvas pb-4">
        <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-[0.2em] mb-1">To</p>
        <p className="font-serif text-lg">{cl.addressed_to}</p>
      </header>
      <div className="space-y-4 text-sm leading-relaxed">
        {cl.paragraphs.map((p, i) => (
          <p key={i}>{p}</p>
        ))}
      </div>
      <footer className="border-t border-canvas pt-4 flex justify-between items-center text-[10px] font-mono text-muted-foreground uppercase tracking-widest">
        <span>{cl.word_count} Words</span>
        <span>{cl.citations.length} Verified Citations</span>
      </footer>
    </article>
  );
}
