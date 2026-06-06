# AskPicky Chrome Companion

The public companion is a low-permission MV3 extension for the local/self-hosted
AskPicky engine.

It supports a manual application-assist flow:

- Highlight a job description or application question, or focus an answer field.
- Open the side panel.
- Send selected text, detected field context, page URL, and optional JD context
  to the local API.
- Review question classification, missing evidence, memory suggestions, polish,
  and the final answer.
- Copy or write the approved answer back explicitly.

Permanent constraints:

- No auto-submit.
- No silent scraping.
- No account pairing.
- No bearer token or provider key in extension storage.
- No private memory recall unless the user enables it.
- Confidence labels are shown for detected question/field context.
- Clipboard fallback is used when write-back confidence is low.

## Local API

The default API base is:

```text
http://localhost:8000
```

The side panel exposes the API base so self-hosters can point the extension at a
different local port. The manifest only grants host permissions for localhost
and 127.0.0.1 by default.

## Detection Strategy

Detection runs in this order:

1. Explicit labels and ARIA labels.
2. ATS adapters for Greenhouse, Lever, and Workday-style application pages.
3. Generic nearby container fallback.
4. Manual highlight/send when confidence is low.

## Tests

The generic detector lives in `src/detector.js`; `src/content.js` is only
Chrome message plumbing. Run:

```sh
npm run --prefix apps/extension test
```

The fixture suite covers explicit labels, contenteditable fields, nearby-label
fallback, Greenhouse/Lever/Workday adapters, uncertain-field write-back,
manifest permission shape, API request contracts, private-memory default-off
behaviour, polish, and approve.
