# AskPicky Chrome Companion

*Last updated 2026-06-02.*

V2 Companion starts with a manual, low-permission MV3 flow:

- User highlights a JD or application question, or focuses an answer field.
- The side panel sends selected text, detected field context, page URL, and optional JD context to the hosted AskPicky API.
- AskPicky returns question classification, what the question tests, rubric nudges, missing evidence, memory suggestions, polish, and final answer.
- User explicitly polishes, approves, copies, or writes the approved answer back.

Permanent constraints:

- No auto-submit.
- No silent scraping.
- No private memory recall unless the user enables it.
- Confidence labels are shown for detected question/field context.
- Clipboard fallback is used when write-back confidence is low.

The extension stores only hosted auth state and local UI preferences in
`chrome.storage.local`. Hosted AskPicky remains the source of truth.

## Detection Strategy

Detection runs in this order:

1. Explicit labels and ARIA labels.
2. ATS adapters for Greenhouse, Lever, and Workday-style application pages.
3. Generic nearby container fallback.
4. Manual highlight/send when confidence is low.

## Auth Bridge

The extension uses hosted Supabase auth rather than a separate extension-only
identity.

1. The side panel opens `https://askpicky.com/extension/connect` with the
   extension id in the query string.
2. The hosted app signs the user in with Supabase and calls
   `/api/extension/pairing-token`.
3. The hosted page sends `ASKPICKY_COMPLETE_PAIRING` to the extension from
   `https://askpicky.com`.
4. The extension exchanges the one-time pairing token plus the Supabase access
   token at `/api/extension/exchange`.
5. The API accepts the exchange only when both credentials resolve to the same
   user, then the extension stores the Supabase bearer in `chrome.storage.local`.

The manifest allows external messages only from `https://askpicky.com/*`.
The hosted connect route is intentionally outside the main workspace shell and
onboarding gate; it only creates the one-time token and hands it to Chrome.

## Detection Tests

The generic detector lives in `src/detector.js`; `src/content.js` is only
Chrome message plumbing. Run:

```sh
npm run --prefix extension test
```

The fixture suite covers explicit labels, contenteditable fields, nearby-label
fallback, Greenhouse/Lever/Workday adapters, uncertain-field write-back,
manifest permission shape, API request contracts, private-memory default-off
behaviour, polish, and approve.
