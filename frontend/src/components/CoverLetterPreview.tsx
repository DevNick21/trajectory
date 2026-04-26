import { Loader2, Sparkles } from "lucide-react";

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
    <Card className="min-h-[28rem]">
      <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0">
        <CardTitle>Custom cover letter</CardTitle>
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
        {output && <Letter cl={output} />}
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
        <p className="text-sm font-medium">No cover letter generated yet</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Tailored to the JD, written in your voice.
        </p>
      </div>
      <Button onClick={onGenerate}>
        <Sparkles className="mr-2 h-4 w-4" />
        Generate cover letter
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
      <p className="text-sm text-muted-foreground">Drafting…</p>
    </div>
  );
}

function Letter({ cl }: { cl: CoverLetterOutput }) {
  return (
    <article className="space-y-4 text-card-foreground">
      <header className="border-b pb-3">
        <p className="text-sm text-muted-foreground">To</p>
        <p className="font-medium">{cl.addressed_to}</p>
      </header>
      <div className="space-y-3 text-sm leading-relaxed">
        {cl.paragraphs.map((p, i) => (
          <p key={i}>{p}</p>
        ))}
      </div>
      <footer className="border-t pt-3 text-xs text-muted-foreground">
        {cl.word_count} words · {cl.citations.length} citations
      </footer>
    </article>
  );
}
