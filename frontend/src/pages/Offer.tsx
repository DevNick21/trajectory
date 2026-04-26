// Offer-letter analyser standalone page.
//
// Two routes wire here:
//   GET /offer                 — standalone (no session attached)
//   GET /offer?session=<id>    — session-aware (richer market comparison)
//
// Per-session use is also surfaced inside SessionDetail; this page is
// for the case where the user wants to analyse an offer without going
// through Phase 1 first (e.g. an unsolicited offer arrived).

import { useSearchParams } from "react-router-dom";

import OfferAnalyser from "@/components/OfferAnalyser";

export default function Offer() {
  const [params] = useSearchParams();
  const sessionId = params.get("session") ?? undefined;

  return (
    <div className="space-y-4 max-w-3xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Offer analyser</h1>
        <p className="text-sm text-muted-foreground">
          Forward an offer letter (PDF or pasted text). Every clause is
          parsed and cited to a page; market comparison runs against ASHE
          + the sponsor register when a session is attached.
        </p>
      </div>
      <OfferAnalyser sessionId={sessionId} />
    </div>
  );
}
