# AskPicky Chrome Companion

*Last updated 2026-06-02.*

V2 Companion starts with a manual, low-permission MV3 flow:

- User highlights a JD or application question, or focuses an answer field.
- The side panel sends selected text, detected field context, page URL, and optional JD context to the hosted AskPicky API.
- AskPicky returns question classification, rubric nudges, memory suggestions, polish, and final answer.
- User explicitly copies or writes the approved answer back.

Permanent constraints:

- No auto-submit.
- No silent scraping.
- No private memory recall unless the user enables it.
- Confidence labels are shown for detected question/field context.
- Clipboard fallback is used when write-back confidence is low.

The extension stores only hosted auth state and local UI preferences in
`chrome.storage.local`. Hosted AskPicky remains the source of truth.

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

## Detection Tests

The generic detector lives in `src/detector.js`; `src/content.js` is only
Chrome message plumbing. Run:

```sh
npm run --prefix extension test
```

The fixture suite covers explicit labels, contenteditable fields, nearby-label
fallback, uncertain-field write-back, and manifest permission shape.
