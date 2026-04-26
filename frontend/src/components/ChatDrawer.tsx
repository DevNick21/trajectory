// Natural-language chat drawer (PROCESS Entry 45).
//
// Slides in from the right on every page. Mirrors the Telegram bot's
// natural-language entrypoint: type any message, intent_router classifies,
// the backend either redirects you to a dedicated page (forward_job →
// streaming view; draft_* → /sessions/{id}/{pack}; analyse_offer → /offer)
// or responds inline (chitchat / profile_query / draft_reply).
//
// Per-page state is local. Conversation isn't persisted — the user has
// the dashboard, queue, session detail pages for navigation; this is
// just the natural-language seam.

import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, MessageSquare, Send, X } from "lucide-react";

import { ApiError, sendChat } from "@/lib/api";
import type { ChatResponse } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Turn {
  role: "user" | "assistant";
  text: string;
  reply_kind?: ChatResponse["reply_kind"];
  redirect_to?: string | null;
  payload?: Record<string, unknown> | null;
  intent?: string;
}

interface Props {
  sessionId?: string;        // optional context — pre-fills the chat call
  className?: string;
}

export default function ChatDrawer({ sessionId, className }: Props) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 1e9, behavior: "smooth" });
  }, [turns]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setTurns((t) => [...t, { role: "user", text }]);
    setBusy(true);
    try {
      const resp = await sendChat(text, sessionId);
      setTurns((t) => [...t, {
        role: "assistant",
        text: resp.text ?? "",
        reply_kind: resp.reply_kind,
        redirect_to: resp.redirect_to,
        payload: resp.payload,
        intent: resp.intent,
      }]);
      if (resp.reply_kind === "redirect" && resp.redirect_to) {
        // Give the user a beat to read the assistant's reply, then jump.
        setTimeout(() => navigate(resp.redirect_to!), 800);
      }
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message
        : err instanceof Error ? err.message
        : "Chat failed.";
      setTurns((t) => [...t, { role: "assistant", text: `⚠️ ${message}` }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {/* Floating launcher */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "fixed bottom-6 right-6 z-30 flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg hover:bg-primary/90 transition-transform hover:scale-105",
          open && "opacity-0 pointer-events-none",
          className,
        )}
        aria-label="Open chat"
      >
        <MessageSquare className="h-5 w-5" />
      </button>

      {/* Drawer */}
      <div
        className={cn(
          "fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l bg-background shadow-2xl transition-transform",
          open ? "translate-x-0" : "translate-x-full",
        )}
        aria-hidden={!open}
      >
        <header className="flex items-center justify-between border-b px-4 py-3">
          <div>
            <h2 className="font-semibold tracking-tight">Chat</h2>
            <p className="text-xs text-muted-foreground">
              Natural-language entry — same as the Telegram bot.
            </p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setOpen(false)}
            aria-label="Close chat"
          >
            <X className="h-4 w-4" />
          </Button>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
          {turns.length === 0 && (
            <div className="text-sm text-muted-foreground space-y-2">
              <p>Try one of:</p>
              <ul className="list-disc list-inside text-xs space-y-1">
                <li>"Forward this: https://boards.greenhouse.io/..."</li>
                <li>"draft me a CV for that Acme role"</li>
                <li>"what should I ask for in salary?"</li>
                <li>"reply to this recruiter: ..."</li>
                <li>"show my recent sessions"</li>
              </ul>
            </div>
          )}
          {turns.map((t, i) => (
            <div
              key={i}
              className={cn(
                "rounded-md p-3 text-sm whitespace-pre-wrap",
                t.role === "user"
                  ? "bg-primary/10 border border-primary/30 ml-6"
                  : "bg-secondary/40 border border-secondary/60 mr-6",
              )}
            >
              {t.text}
              {t.intent && t.role === "assistant" && (
                <div className="mt-1 text-[10px] text-muted-foreground">
                  intent: {t.intent}
                  {t.redirect_to && ` · navigating to ${t.redirect_to}`}
                </div>
              )}
            </div>
          ))}
          {busy && (
            <div className="rounded-md bg-secondary/40 border p-3 mr-6 flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              thinking…
            </div>
          )}
        </div>

        <form
          onSubmit={onSubmit}
          className="border-t p-3 flex items-center gap-2"
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message…"
            className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            disabled={busy}
            autoComplete="off"
          />
          <Button type="submit" size="sm" disabled={busy || !input.trim()}>
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </div>
    </>
  );
}
