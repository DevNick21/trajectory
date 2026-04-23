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

    Tolerates both dict and SDK-object content blocks. Ignores any
    block whose `type` isn't `text`.
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
        if btype != "text":
            continue
        txt = _get(block, "text")
        if isinstance(txt, str):
            out.append(txt)
    return out


def _parse_final_json(text: str) -> Optional[dict]:
    """Best-effort parse of the final agent message as JSON.

    The agent is instructed to emit raw JSON. Tolerate markdown fences
    (```json ... ```) because LLMs sometimes slip them in.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        return None
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
    """
    # Most SDKs expose `content` as a list of blocks. Try that first.
    content = _get(tool_result, "content")
    all_text = "\n".join(_text_blocks(content))
    # Some event shapes expose `output` or `result` instead.
    if not all_text:
        output = _get(tool_result, "output", "result", "data")
        if isinstance(output, str):
            all_text = output
        elif isinstance(output, dict):
            all_text = json.dumps(output)

    # Try to find a URL on the result event first; then in the body
    # text; then fall back to whatever URL the tool_use carried.
    url = _get(tool_result, "url", "source_url")
    if not isinstance(url, str):
        match = _URL_RE.search(all_text) if all_text else None
        url = match.group(0) if match else None
    if not url and fallback_url:
        url = fallback_url

    if not url:
        return None

    text_hash_seed = (all_text or "")[:4000]
    return ScrapedPage(
        url=url,
        fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
        text=all_text or "",
        text_hash=f"ma-{hash(text_hash_seed) & 0xFFFF_FFFF:08x}",
    )


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

    return result
