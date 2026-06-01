# AskPicky Chrome Companion

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
