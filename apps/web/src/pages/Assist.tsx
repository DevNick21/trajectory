import { useMemo, useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Check,
  ClipboardCheck,
  Loader2,
  MessageSquareText,
  Search,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";

import {
  approveAssistAnswer,
  critiqueAssistDraft,
  polishAssistAnswer,
  suggestAssistMemory,
  startAssistSession,
} from "@/lib/api";
import type {
  AnswerCritique,
  ApplicationAnswerOutput,
  MemorySuggestion,
  QuestionPattern,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export default function Assist() {
  const [companyName, setCompanyName] = useState("");
  const [roleTitle, setRoleTitle] = useState("");
  const [jdText, setJdText] = useState("");
  const [questionText, setQuestionText] = useState("");
  const [rawDraft, setRawDraft] = useState("");
  const [wordLimit, setWordLimit] = useState("");
  const [privateMode, setPrivateMode] = useState(true);
  const [includePrivate, setIncludePrivate] = useState(false);
  const [assistSessionId, setAssistSessionId] = useState<string | null>(null);
  const [attemptId, setAttemptId] = useState<string | null>(null);
  const [pattern, setPattern] = useState<QuestionPattern | null>(null);
  const [suggestions, setSuggestions] = useState<MemorySuggestion[]>([]);
  const [critique, setCritique] = useState<AnswerCritique | null>(null);
  const [polished, setPolished] = useState<ApplicationAnswerOutput | null>(null);
  const [saveIndicator, setSaveIndicator] = useState<string | null>(null);

  const wordLimitNumber = useMemo(() => {
    const n = Number(wordLimit);
    return Number.isFinite(n) && n > 0 ? n : null;
  }, [wordLimit]);

  const selectedMemoryIds = () => suggestions.slice(0, 3).map((s) => s.memory_id);

  const clearSessionState = () => {
    setAssistSessionId(null);
    setAttemptId(null);
    setPattern(null);
    setSuggestions([]);
    setCritique(null);
    setPolished(null);
    setSaveIndicator(null);
  };

  const ensureAssistSession = async () => {
    if (assistSessionId) return assistSessionId;
    const data = await startAssistSession({
      company_name: companyName.trim() || null,
      role_title: roleTitle.trim() || null,
      jd_text: jdText.trim() || null,
      private_mode: privateMode,
    });
    const id = data.assist_session.assist_session_id;
    setAssistSessionId(id);
    return id;
  };

  const basePayload = async () => ({
    assist_session_id: await ensureAssistSession(),
    question_text: questionText,
    jd_text: jdText,
    raw_draft: rawDraft,
    word_limit: wordLimitNumber,
    include_private: includePrivate,
    selected_memory_ids: selectedMemoryIds(),
  });

  const suggest = useMutation({
    mutationFn: async () =>
      suggestAssistMemory({
        assist_session_id: await ensureAssistSession(),
        question_text: questionText,
        jd_text: jdText,
        k: 5,
        include_private: includePrivate,
      }),
    onSuccess: (data) => {
      setPattern(data.pattern);
      setSuggestions(data.suggestions);
    },
    onError: () => toast.error("Could not analyse this question."),
  });

  const critiqueMutation = useMutation({
    mutationFn: async () => critiqueAssistDraft(await basePayload()),
    onSuccess: (data) => {
      setAttemptId(data.attempt_id);
      setCritique(data.critique);
      setSaveIndicator(data.save_indicator);
    },
    onError: () => toast.error("Could not check this draft."),
  });

  const polish = useMutation({
    mutationFn: async () =>
      polishAssistAnswer({
        ...(await basePayload()),
        attempt_id: attemptId,
      }),
    onSuccess: (data) => {
      setAttemptId(data.attempt_id);
      setPolished(data.output);
      setSaveIndicator(data.output.save_indicator);
    },
    onError: () => toast.error("Could not polish this answer."),
  });

  const approve = useMutation({
    mutationFn: () =>
      approveAssistAnswer({
        attempt_id: attemptId ?? "",
        final_answer: polished?.final_answer || rawDraft,
        selected_memory_ids: selectedMemoryIds(),
      }),
    onSuccess: (data) => {
      setSaveIndicator(data.save_indicator);
      toast.success(`${data.memory_items_created} memory item(s) sent to inbox.`);
    },
    onError: () => toast.error("Could not approve this answer."),
  });

  const canAnalyse = questionText.trim().length > 0;
  const canCheck = canAnalyse && rawDraft.trim().length > 0;
  const critiquePct = critique
    ? Math.round(
        (critique.scores.reduce((sum, score) => sum + score.score, 0)
          / Math.max(1, critique.scores.length * 5))
          * 100,
      )
    : 0;

  return (
    <div className="mx-auto grid max-w-7xl gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(360px,0.95fr)]">
      <section className="space-y-4">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs font-mono uppercase tracking-[0.3em] text-muted-foreground">
              Application Assist
            </p>
            <h1 className="font-serif text-4xl">Question Workspace</h1>
          </div>
          {saveIndicator && <Badge variant="secondary">{saveIndicator}</Badge>}
        </header>

        <Card className="border-canvas bg-card/80">
          <CardHeader>
            <CardTitle className="text-base">Context</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Field label="Job description">
              <textarea
                value={jdText}
                onChange={(event) => {
                  setJdText(event.target.value);
                  clearSessionState();
                }}
                className="min-h-36 w-full resize-y rounded-lg border border-canvas bg-background px-3 py-2 text-sm outline-none ring-primary/30 transition focus:ring-2"
                placeholder="Paste the JD or the relevant section."
              />
            </Field>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Company">
                <Input
                  value={companyName}
                  onChange={(event) => {
                    setCompanyName(event.target.value);
                    clearSessionState();
                  }}
                  placeholder="Company name"
                />
              </Field>
              <Field label="Role">
                <Input
                  value={roleTitle}
                  onChange={(event) => {
                    setRoleTitle(event.target.value);
                    clearSessionState();
                  }}
                  placeholder="Role title"
                />
              </Field>
            </div>
            <Field label="Application question">
              <textarea
                value={questionText}
                onChange={(event) => {
                  setQuestionText(event.target.value);
                  setAttemptId(null);
                  setPattern(null);
                  setSuggestions([]);
                  setCritique(null);
                  setPolished(null);
                  setSaveIndicator(null);
                }}
                className="min-h-24 w-full resize-y rounded-lg border border-canvas bg-background px-3 py-2 text-sm outline-none ring-primary/30 transition focus:ring-2"
                placeholder="Paste the question you need to answer."
              />
            </Field>
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Word limit">
                <Input
                  value={wordLimit}
                  onChange={(event) => setWordLimit(event.target.value)}
                  inputMode="numeric"
                  className="w-32"
                  placeholder="200"
                />
              </Field>
              <Button disabled={!canAnalyse || suggest.isPending} onClick={() => suggest.mutate()}>
                {suggest.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Search className="mr-2 h-4 w-4" aria-hidden />
                )}
                Analyse
              </Button>
              <label className="flex min-h-10 items-center gap-2 rounded-lg border border-canvas px-3 text-sm">
                <input
                  type="checkbox"
                  aria-label="Private save"
                  checked={privateMode}
                  onChange={(event) => {
                    setPrivateMode(event.target.checked);
                    clearSessionState();
                  }}
                  className="h-4 w-4"
                />
                Private save
              </label>
              <label className="flex min-h-10 items-center gap-2 rounded-lg border border-canvas px-3 text-sm">
                <input
                  type="checkbox"
                  aria-label="Include private memory"
                  checked={includePrivate}
                  onChange={(event) => setIncludePrivate(event.target.checked)}
                  className="h-4 w-4"
                />
                Include private memory
              </label>
            </div>
          </CardContent>
        </Card>

        <Card className="border-canvas bg-card/80">
          <CardHeader>
            <CardTitle className="text-base">Draft</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <textarea
              value={rawDraft}
              onChange={(event) => {
                setRawDraft(event.target.value);
                setAttemptId(null);
                setCritique(null);
                setPolished(null);
                setSaveIndicator(null);
              }}
              className="min-h-48 w-full resize-y rounded-lg border border-canvas bg-background px-3 py-2 text-sm outline-none ring-primary/30 transition focus:ring-2"
              placeholder="Write or paste your rough answer."
            />
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={!canCheck || critiqueMutation.isPending}
                onClick={() => critiqueMutation.mutate()}
              >
                {critiqueMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <ClipboardCheck className="mr-2 h-4 w-4" aria-hidden />
                )}
                Check
              </Button>
              <Button
                variant="secondary"
                disabled={!canCheck || polish.isPending}
                onClick={() => polish.mutate()}
              >
                {polish.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Sparkles className="mr-2 h-4 w-4" aria-hidden />
                )}
                Polish
              </Button>
              <Button
                variant="outline"
                disabled={!attemptId || approve.isPending}
                onClick={() => approve.mutate()}
              >
                {approve.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Check className="mr-2 h-4 w-4" aria-hidden />
                )}
                {polished ? "Approve polished answer" : "Approve draft as final"}
              </Button>
            </div>
          </CardContent>
        </Card>
      </section>

      <aside className="space-y-4">
        {pattern && (
          <Card className="border-canvas bg-card/80">
            <CardHeader className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{pattern.question_type}</Badge>
                <Badge variant="outline">{pattern.confidence}</Badge>
              </div>
              <CardTitle className="text-base capitalize">
                {pattern.question_type.replace("_", " ")}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <p className="leading-relaxed text-foreground/90">{pattern.what_testing}</p>
              <KeyValueList title="Expected evidence" values={pattern.ideal_evidence} />
              <KeyValueList title="Structure" values={[pattern.structure_hint]} />
              <KeyValueList title="Common failures" values={pattern.common_failures} />
            </CardContent>
          </Card>
        )}

        <Card className="border-canvas bg-card/80">
          <CardHeader>
            <CardTitle className="text-base">Best Story Angles</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {suggestions.length === 0 ? (
              <p className="text-sm text-muted-foreground">No approved memory matched yet.</p>
            ) : (
              suggestions.map((item) => (
                <div key={item.memory_id} className="rounded-lg border border-canvas p-3">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{item.memory_kind.replace("_", " ")}</Badge>
                    {item.outcome_signal === "positive" && (
                      <Badge variant="success">interview signal</Badge>
                    )}
                    {item.warnings.map((warning) => (
                      <Badge key={warning} variant="warning">
                        {warning}
                      </Badge>
                    ))}
                  </div>
                  <p className="text-sm font-medium">{item.title}</p>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{item.text}</p>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        {critique && (
          <Card className="border-canvas bg-card/80">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <MessageSquareText className="h-4 w-4" aria-hidden />
                Draft Check
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <div className="flex flex-wrap gap-2">
                <Badge variant={critiquePct >= 70 ? "success" : "warning"}>{critiquePct}%</Badge>
                <Badge variant="secondary">{critique.word_count} words</Badge>
                <Badge variant="outline">{critique.word_limit_status}</Badge>
              </div>
              {critique.targeted_nudge && (
                <p className="leading-relaxed text-foreground/90">{critique.targeted_nudge}</p>
              )}
              <KeyValueList title="Missing evidence" values={critique.missing_evidence} />
              <div className="grid gap-2 sm:grid-cols-2">
                {critique.scores.map((score) => (
                  <div key={score.dimension} className="rounded-lg border border-canvas p-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
                        {score.dimension.replace("_", " ")}
                      </span>
                      <span className="font-mono text-xs">{Math.round((score.score / 5) * 100)}%</span>
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{score.note}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {polished && (
          <Card className="border-canvas bg-card/80">
            <CardHeader>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{polished.word_count} words</Badge>
                <Badge variant="secondary">{polished.question_type}</Badge>
              </div>
              <CardTitle className="text-base">Final Answer</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <p className="whitespace-pre-wrap leading-relaxed text-foreground/90">
                {polished.final_answer}
              </p>
              <KeyValueList title="Structure" values={[polished.structure_used]} />
              <KeyValueList title="Missing evidence" values={polished.missing_evidence_flags} />
            </CardContent>
          </Card>
        )}
      </aside>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-2">
      <span className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </span>
      {children}
    </label>
  );
}

function KeyValueList({ title, values }: { title: string; values: string[] }) {
  if (!values.length) return null;
  return (
    <div>
      <p className="mb-2 text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
        {title}
      </p>
      <ul className="space-y-1 text-sm leading-relaxed text-muted-foreground">
        {values.map((value) => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </div>
  );
}
