"""Event-stream processing for a Managed Agents session.

Consumes the async iterator from `client.beta.sessions.events.stream`
and produces:
  - `scraped_pages`: every URL the agent fetched, with raw text
  - `final_json`: dict from the agent's final message (or None if
    the session ended before emitting final JSON)
  - `terminated_early`: True if the stream ended on
    `session.status_terminated` or `session.error`
  - `input_tokens` / `output_tokens`: best-effort accumulator; the
    authoritative value is `sessions.retrieve(id).usage`, which the
    investigator reads after the stream closes.

Events we handle:
  - `agent.message` — text blocks. The LAST `agent.message` is
    parsed as the final JSON output.
  - `agent.tool_use` — records what the agent called.
  - `agent.tool_result` — captures URL + body text where available
    (web_fetch results).
  - `session.status_idle` — break (normal termination).
  - `session.status_terminated`, `session.error` — break with
    `terminated_early=True`.
  - `span.model_request_end` — incremental token usage.

Events we ignore: `agent.thinking`, `session.status_running`,
`session.status_rescheduled`, `span.model_request_start`,
anything multi-agent or outcome-related.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from ..schemas import ScrapedPage

logger = logging.getLogger(__name__)


@dataclass
class EventStreamResult:
    scraped_pages: list[ScrapedPage] = field(default_factory=list)
    final_json: Optional[dict] = None
    terminated_early: bool = False
    terminated_reason: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    # Debug: track what the agent did
    tool_call_trace: list[str] = field(default_factory=list)
    # Diagnostic: surface enough state on the result that callers can
    # write helpful failure messages when `final_json is None`. Without
    # these, "agent did not emit a parseable JSON final message" is
    # ambiguous — could be "no agent.message events at all", "messages
    # but no text blocks", or "text but unparseable".
    agent_message_count: int = 0
    last_agent_text_preview: Optional[str] = None


_URL_RE = re.compile(r"https?://[^\s<>\"']+")


def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Attribute-or-key lookup tolerant of both SDK objects and plain dicts."""
    for key in keys:
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
        elif hasattr(obj, key):
            val = getattr(obj, key)
            if val is not None:
                return val
    return default


def _text_blocks(content: Any) -> list[str]:
    """Flatten a message's content array to a list of text strings.

    Tolerates both dict and SDK-object content blocks. Recognises:
      - `{type: "text", text: "..."}` — the documented chat shape
      - `{type: "document", source: {type: "text", data: "..."}}` —
        the Anthropic Managed Agents `BetaManagedAgentsDocumentBlock`
        shape (web_fetch tool results in the live SDK as of 2026-04-25;
        observed via `_extract_scraped_page`'s empty-body warning in
        PROCESS Entry 46).
      - SDK-object equivalents of both via attribute access.
    """
    out: list[str] = []
    if content is None:
        return out
    try:
        items: Iterable[Any] = content
    except TypeError:
        return out
    for block in items:
        btype = _get(block, "type")
        if btype == "text":
            txt = _get(block, "text")
            if isinstance(txt, str):
                out.append(txt)
        elif btype == "document":
            # `block.source` is a typed object whose `data` carries the
            # page body. Class names observed in production:
            # BetaManagedAgentsDocumentBlock + BetaManagedAgentsPlainTextDocumentSource.
            source = _get(block, "source")
            if source is not None:
                data = _get(source, "data", "text")
                if isinstance(data, str):
                    out.append(data)
                elif isinstance(data, list):
                    out.extend(s for s in data if isinstance(s, str))
    return out


def _fix_common_json_malformations(text: str) -> str:
    """Best-effort patch of JSON syntax errors that real models emit.
    Each fix is idempotent and preserves valid JSON unchanged.

    Currently fixes:
      1. Trailing commas before `]` or `}` (`[1, 2,]` → `[1, 2]`).
         Tolerated by JSON5 / many other parsers; strict json.loads
         rejects.
      2. Missing comma between adjacent string-quoted values inside
         an object (`"a": "x" "b": "y"` → `"a": "x", "b": "y"`).
         Surfaced by `managed_investigator` live runs (PROCESS Entry
         47 bug 23) — Opus occasionally drops the inter-pair comma.
    """
    # Trailing commas: `,\s*}` → `}`, `,\s*]` → `]`. Use re.sub.
    text = re.sub(r",(\s*[}\]])", r"\1", text)

    # Missing comma between adjacent values: pattern is
    # `"<value>"\s*\n\s*"<key>"` inside an object — i.e. a quote-end
    # followed (after whitespace) by a quote-start where we'd expect
    # a comma. We only insert a comma when we can confirm the second
    # quote opens a key (followed by `:`).
    # Conservative regex: end of value `"` then whitespace, then key
    # `"...":`. Insert comma after the first `"`.
    text = re.sub(
        r'("(?:[^"\\]|\\.)*")(\s+)("(?:[^"\\]|\\.)*"\s*:)',
        r"\1,\2\3",
        text,
    )
    return text


def _escape_unescaped_control_chars_in_strings(text: str) -> str:
    """Walk the text and escape literal control characters (raw 0x09
    tab, raw 0x0A newline, raw 0x0D carriage return) that appear
    *inside* JSON string values. Outside strings they're whitespace
    and json.loads accepts them; inside strings they're a syntax
    error per the JSON spec but real models routinely emit them
    (PROCESS Entry 47 bug 18 — managed_reviews_investigator's
    `text` fields contain raw newlines from copy-pasted reviews).
    """
    out: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            if escape:
                out.append(ch)
                escape = False
            elif ch == "\\":
                out.append(ch)
                escape = True
            elif ch == '"':
                out.append(ch)
                in_string = False
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            elif ord(ch) < 0x20:
                out.append(f"\\u{ord(ch):04x}")
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
    return "".join(out)


def _parse_final_json(text: str) -> Optional[dict]:
    """Best-effort parse of the final agent message as JSON.

    The agent is instructed to emit raw JSON. We try, in order:
      1. Strip markdown fences (```json ... ```) and parse.
      2. Parse verbatim.
      3. Re-parse with raw control chars in strings escaped (real
         models routinely emit raw newlines inside `text` fields
         when paraphrasing reviews / page bodies).
      4. Find the largest balanced `{...}` substring and parse that —
         catches the common case where the agent prepends a sentence
         like "Here is the final output:" before the JSON, or appends
         "Let me know if you need anything else." after.

    Returns None when no candidate parses to a dict.
    """
    candidates: list[str] = []

    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        candidates.append("\n".join(lines).strip())
    candidates.append(stripped)
    # Defence against raw control characters inside string values —
    # try a sanitized variant of every candidate above.
    candidates.append(_escape_unescaped_control_chars_in_strings(stripped))

    # Brace-balanced extraction: scan for the first `{`, then track
    # depth (skipping over strings) until the matching `}`. Picks the
    # *largest* such object, so a tiny `{}` inside an explanation
    # doesn't beat the real payload that follows.
    largest: Optional[str] = None
    i = 0
    n = len(stripped)
    while i < n:
        if stripped[i] == "{":
            depth = 0
            in_string = False
            escape = False
            j = i
            while j < n:
                ch = stripped[j]
                if in_string:
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_string = False
                else:
                    if ch == '"':
                        in_string = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            sub = stripped[i : j + 1]
                            if largest is None or len(sub) > len(largest):
                                largest = sub
                            break
                j += 1
            i = j + 1
        else:
            i += 1
    if largest is not None and largest not in candidates:
        candidates.append(largest)
        # Also try the sanitized form of the extracted block — agents
        # routinely emit prose-then-JSON where the JSON contains raw
        # newlines (PROCESS Entry 47 bug 18b). Without this, the
        # extracted block fails json.loads even though it's exactly
        # the JSON we want to parse.
        sanitized_largest = _escape_unescaped_control_chars_in_strings(
            largest
        )
        if sanitized_largest not in candidates:
            candidates.append(sanitized_largest)

    # Last-resort permissive span: from the FIRST `{` to the LAST `}`.
    # The brace-balance scanner above can be defeated by an unescaped
    # `"` inside a long string value — the in_string state flips early,
    # the depth counter goes wrong, and the "balanced" block it picks
    # is too short to contain the real payload. The full first-to-last
    # span is the broadest sanitization target and almost always
    # covers the real JSON when the structured one missed.
    first_open = stripped.find("{")
    last_close = stripped.rfind("}")
    if (
        first_open != -1
        and last_close > first_open
    ):
        full_span = stripped[first_open : last_close + 1]
        if full_span not in candidates:
            candidates.append(full_span)
        sanitized_full = _escape_unescaped_control_chars_in_strings(full_span)
        if sanitized_full not in candidates:
            candidates.append(sanitized_full)

    # Add malformation-fix variants of every candidate so far.
    # Bug 24: trailing commas / missing commas between adjacent values
    # are real Opus-emission patterns; both are cheap to patch.
    fixed_candidates: list[str] = []
    for c in list(candidates):
        f = _fix_common_json_malformations(c)
        if f != c and f not in candidates:
            fixed_candidates.append(f)
    candidates.extend(fixed_candidates)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _extract_scraped_page(
    tool_result: Any,
    *,
    fallback_url: Optional[str] = None,
) -> Optional[ScrapedPage]:
    """Extract URL + text from an `agent.tool_result` event, if it
    looks like a web_fetch result.

    `fallback_url` is the URL captured from the originating
    `agent.tool_use` event — used when the result body doesn't expose
    its own URL. Returns None only when there's neither a URL nor
    body text to record.

    Tries the following content shapes in order until one yields text:
      1. `content`: list of `{type, text}` blocks (the documented shape).
      2. `output` / `result` / `data` (string or dict — when the SDK
         flattens the response into a single field).
      3. `body` / `text` directly on the event (some web_fetch
         variants expose the page body inline).
      4. `content` as a string (some SDK versions flatten inline).
      5. Recursive scan of any nested dicts/lists for `text` fields,
         capped to `_MAX_NESTED_TEXT_CHARS` so a malformed event doesn't
         dump unbounded JSON into `scraped_pages.text`.

    A warning is logged when we end up with an empty body for a known
    URL — the citation validator's downstream "snippet not in haystack"
    failure (with `haystack=0c`) was masking this content-extraction
    miss in PROCESS Entry 46's full live run.
    """
    # 1. Documented shape: list of content blocks.
    content = _get(tool_result, "content")
    all_text = "\n".join(_text_blocks(content))

    # 2. Flat string / dict on the event.
    if not all_text:
        output = _get(tool_result, "output", "result", "data")
        if isinstance(output, str):
            all_text = output
        elif isinstance(output, dict):
            all_text = json.dumps(output)

    # 3. Body / text fields directly on the event.
    if not all_text:
        body = _get(tool_result, "body", "text")
        if isinstance(body, str):
            all_text = body
        elif isinstance(body, dict):
            all_text = json.dumps(body)

    # 4. Some SDK versions return content as a string instead of a list.
    if not all_text and isinstance(content, str):
        all_text = content

    # 5. Last-resort recursive scan — pulls every `text` field out of
    # nested objects until we hit the cap. Catches event shapes the
    # explicit fields above miss.
    if not all_text:
        all_text = _recursive_text_extract(tool_result)

    # Try to find the URL of THIS page in this priority order:
    #   1. Direct `url` / `source_url` field on the result event.
    #   2. The fallback URL from the originating `agent.tool_use` event
    #      (the URL passed to `web_fetch`). Crucial: prefer this over
    #      body regex because for any HTML page the first URL in the
    #      body is a link FROM the page (`href` in nav / footer), not
    #      the page's own URL. Storing under the body-link URL meant
    #      citations referencing the actual source URL couldn't resolve
    #      — surfaced live via PROCESS Entry 46's full run.
    #   3. As a last resort, regex-search the body for any URL.
    url = _get(tool_result, "url", "source_url")
    if not isinstance(url, str):
        if fallback_url:
            url = fallback_url
        elif all_text:
            match = _URL_RE.search(all_text)
            url = match.group(0) if match else None

    if not url:
        return None

    if not all_text:
        # Loud warning so the next run's logs pin down the missing
        # extraction shape — comparing snippets against an empty
        # haystack is always a failure.
        logger.warning(
            "_extract_scraped_page: empty body for url=%s — "
            "tool_result event shape didn't match any known content "
            "field. Dump (truncated): %r",
            url, repr(tool_result)[:500],
        )

    text_hash_seed = (all_text or "")[:4000]
    return ScrapedPage(
        url=url,
        fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
        text=all_text or "",
        text_hash=f"ma-{hash(text_hash_seed) & 0xFFFF_FFFF:08x}",
    )


_MAX_NESTED_TEXT_CHARS = 200_000


def _recursive_text_extract(obj: Any) -> str:
    """Walk a tool_result object and concatenate every `text` field we
    find, capped to `_MAX_NESTED_TEXT_CHARS`. Used as a last resort
    when the explicit content/output/body fields all came up empty."""
    parts: list[str] = []
    total = 0

    def _walk(node: Any) -> bool:
        nonlocal total
        if total >= _MAX_NESTED_TEXT_CHARS:
            return False
        if isinstance(node, dict):
            txt = node.get("text") if "text" in node else None
            if isinstance(txt, str):
                parts.append(txt)
                total += len(txt)
                if total >= _MAX_NESTED_TEXT_CHARS:
                    return False
            for v in node.values():
                if not _walk(v):
                    return False
        elif isinstance(node, list):
            for item in node:
                if not _walk(item):
                    return False
        elif hasattr(node, "__dict__"):
            # SDK objects: walk their attributes but skip dunder/private.
            for k in dir(node):
                if k.startswith("_"):
                    continue
                try:
                    v = getattr(node, k)
                except Exception:
                    continue
                if callable(v):
                    continue
                if k == "text" and isinstance(v, str):
                    parts.append(v)
                    total += len(v)
                    if total >= _MAX_NESTED_TEXT_CHARS:
                        return False
                elif isinstance(v, (dict, list)):
                    if not _walk(v):
                        return False
                elif hasattr(v, "__dict__") and not isinstance(v, type):
                    # Recurse into nested SDK-like objects (but skip
                    # class objects, which would walk their methods).
                    if not _walk(v):
                        return False
        return True

    _walk(obj)
    return "\n".join(p for p in parts if p)


def _extract_tool_use_url(tool_use: Any) -> Optional[str]:
    """If the agent called web_fetch, return the URL it passed."""
    tool_input = _get(tool_use, "input", "arguments")
    if isinstance(tool_input, dict):
        url = tool_input.get("url")
        if isinstance(url, str):
            return url
    return None


async def consume_stream(stream: Any) -> EventStreamResult:
    """Iterate the stream until terminal. Returns an EventStreamResult.

    Expects `stream` to be an async-iterable of events (either dicts or
    SDK objects). Breaks on idle / terminated / error.
    """
    result = EventStreamResult()
    last_agent_text: Optional[str] = None
    pending_tool_use_urls: dict[str, str] = {}

    async for event in stream:
        etype = _get(event, "type")

        if etype == "agent.message":
            result.agent_message_count += 1
            texts = _text_blocks(_get(event, "content"))
            if texts:
                last_agent_text = "\n".join(texts)

        elif etype == "agent.tool_use":
            tool_name = _get(event, "name") or "?"
            result.tool_call_trace.append(f"tool_use:{tool_name}")
            tool_use_id = _get(event, "id", "tool_use_id")
            url = _extract_tool_use_url(event)
            if isinstance(tool_use_id, str) and isinstance(url, str):
                pending_tool_use_urls[tool_use_id] = url

        elif etype == "agent.tool_result":
            tool_use_id = _get(event, "tool_use_id", "id")
            fallback = (
                pending_tool_use_urls.get(tool_use_id)
                if isinstance(tool_use_id, str)
                else None
            )
            page = _extract_scraped_page(event, fallback_url=fallback)
            if page is not None:
                result.scraped_pages.append(page)

        elif etype == "span.model_request_end":
            usage = _get(event, "model_usage", "usage")
            if usage is not None:
                it = _get(usage, "input_tokens")
                ot = _get(usage, "output_tokens")
                if isinstance(it, int):
                    result.input_tokens += it
                if isinstance(ot, int):
                    result.output_tokens += ot

        elif etype == "session.status_idle":
            break

        elif etype in ("session.status_terminated", "session.error"):
            result.terminated_early = True
            err = _get(event, "error")
            msg = _get(err, "message") if err is not None else None
            result.terminated_reason = (
                msg if isinstance(msg, str) else f"session ended: {etype}"
            )
            break

    if last_agent_text is not None:
        result.final_json = _parse_final_json(last_agent_text)
        # On parse failure the most useful signal is whether the
        # emission was truncated mid-token (output budget exhausted)
        # or genuinely malformed. Capture both head AND tail of the
        # text plus the total length, so an error like "ends with
        # ...years of pr" instantly rules in/out truncation.
        # When parsing fails despite text that LOOKS complete (ends
        # with `}`), include the json.loads error message — pinpoints
        # the offending offset/token.
        total = len(last_agent_text)
        parse_error_hint = ""
        if result.final_json is None:
            try:
                json.loads(last_agent_text.strip())
            except json.JSONDecodeError as exc:
                # Show ±80 chars around the offending position so the
                # actual malformation is visible without dumping the
                # whole text. PROCESS Entry 47 bug 23 — managed_invest-
                # igator failures with `Expecting ',' delimiter at
                # char N` were opaque without seeing what's at char N.
                pos = getattr(exc, "pos", -1)
                stripped = last_agent_text.strip()
                if 0 <= pos < len(stripped):
                    lo = max(0, pos - 80)
                    hi = min(len(stripped), pos + 80)
                    around = stripped[lo:hi]
                    pointer = " " * (pos - lo) + "^"
                    parse_error_hint = (
                        f" [parse error: {exc}; context around char "
                        f"{pos} ({lo}..{hi}): {around!r}\n{pointer}]"
                    )
                else:
                    parse_error_hint = (
                        f" [parse error on whole text: {exc}]"
                    )
            except (ValueError, TypeError) as exc:
                parse_error_hint = f" [parse error on whole text: {exc}]"
        if total <= 1000:
            result.last_agent_text_preview = last_agent_text + parse_error_hint
        else:
            result.last_agent_text_preview = (
                f"{last_agent_text[:600]}\n...[{total - 1000}c omitted]...\n"
                f"{last_agent_text[-400:]}{parse_error_hint}"
            )

    return result
