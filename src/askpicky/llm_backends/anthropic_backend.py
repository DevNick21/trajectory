"""Anthropic Messages API backend via httpx.

Implements the full Messages API surface: structured output via tool_use,
server-side tools (web_search, code_execution), Citations API, and
Beta Files API for PDF uploads.

No anthropic SDK dependency — raw HTTP calls with strict error handling.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx
from pydantic import BaseModel

from .base import BackendError, LLMCallResult, LLMUsage

logger = logging.getLogger(__name__)

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_BASE_URL = "https://api.anthropic.com"

_VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


# ---------------------------------------------------------------------------
# Anthropic Backend
# ---------------------------------------------------------------------------


class AnthropicBackend:
    """Messages API backend for Anthropic models."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 180.0,
    ):
        if not api_key:
            raise BackendError(
                "ANTHROPIC_API_KEY is required for the Anthropic backend."
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
        return self._client

    # ------------------------------------------------------------------
    # Core call — structured output via tool_use
    # ------------------------------------------------------------------

    async def call(
        self,
        *,
        system_prompt: str | list[dict],
        messages: list[dict],
        output_schema: type[BaseModel],
        model: str,
        effort: str = "xhigh",
    ) -> LLMCallResult:
        """Send a Messages API request and extract tool_use.input."""
        tool = _schema_to_tool(output_schema)
        body = self._build_request_body(
            model=model,
            system_prompt=system_prompt,
            messages=messages,
            tools=[tool],
            effort=effort,
            tool_choice=_tool_choice_for(model),
        )

        resp_data = await self._post("/v1/messages", body)
        return self._extract_tool_use_result(resp_data)

    # ------------------------------------------------------------------
    # Multi-turn agentic tool use (CV tailor, managed agents)
    # ------------------------------------------------------------------

    async def call_with_tool_loop(
        self,
        *,
        system_prompt: str | list[dict],
        user_input: str,
        tools: list[dict],
        output_schema: type[BaseModel],
        tool_executor,
        model: str,
        effort: str = "xhigh",
        max_iterations: int = 10,
    ):
        """Multi-turn tool-use loop.

        `tools`: all server-side tools the agent can call.
        The final `emit_structured_output` tool is auto-appended.

        `tool_executor(tool_name, tool_input) -> str`: called each turn
        for every non-emit tool_use. Return the tool result as a string.
        """
        final_tool = _schema_to_tool(output_schema)
        final_tool_name = final_tool["name"]
        all_tools = list(tools) + [final_tool]

        chat_messages: list[dict] = [
            {"role": "user", "content": user_input}
        ]
        total_usage = LLMUsage()

        for turn in range(max_iterations):
            body = self._build_request_body(
                model=model,
                system_prompt=system_prompt,
                messages=chat_messages,
                tools=all_tools,
                effort=effort,
                tool_choice={"type": "auto"},
            )
            resp_data = await self._post("/v1/messages", body)
            total_usage = _accumulate_usage(total_usage, resp_data)

            content_blocks = resp_data.get("content", [])
            tool_uses = [b for b in content_blocks
                         if b.get("type") == "tool_use"]

            # Add assistant response to the chat history.
            chat_messages.append({
                "role": "assistant",
                "content": _preserve_assistant_blocks(content_blocks),
            })

            # Check if the model called the final emit tool.
            final_call = next(
                (tu for tu in tool_uses
                 if tu.get("name") == final_tool_name),
                None,
            )
            if final_call is not None:
                raw = _unwrap_parameter_value(final_call.get("input", {}))
                if not isinstance(raw, dict):
                    raise BackendError(
                        "Final tool_use.input was not a JSON object."
                    )
                return raw, total_usage

            if not tool_uses:
                chat_messages.append({
                    "role": "user",
                    "content": (
                        "You produced a text-only response. Please either "
                        "call one of the provided tools or emit the final "
                        f"{output_schema.__name__} via the "
                        f"`{final_tool_name}` tool."
                    ),
                })
                continue

            # Execute all non-final tool calls.
            result_blocks = []
            for tu in tool_uses:
                tool_name = tu.get("name", "")
                tool_use_id = tu.get("id", "")
                tool_input = tu.get("input", {}) or {}
                try:
                    result = await tool_executor(tool_name, tool_input)
                except Exception as exc:
                    logger.warning(
                        "Tool %s raised: %r", tool_name, exc,
                    )
                    result = f"ERROR: tool {tool_name} failed: {exc}"
                result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result,
                })
            chat_messages.append({
                "role": "user", "content": result_blocks,
            })

        raise BackendError(
            f"Agent exceeded max_iterations={max_iterations} "
            f"without emitting final {output_schema.__name__}."
        )

    # ------------------------------------------------------------------
    # Citations API
    # ------------------------------------------------------------------

    async def call_with_citations(
        self,
        *,
        system_prompt: str | list[dict],
        user_input: str,
        documents: list[dict],
        model: str,
        effort: str = "xhigh",
        extra_tools: Optional[list[dict]] = None,
        cache_documents: bool = True,
    ) -> tuple[list[dict], list[dict], LLMUsage, str]:
        """Citations-API call returning (text_blocks, raw_citations, usage, body).

        `documents` are our domain citation documents. They get wrapped
        into Anthropic's `/v1/messages` document format with
        `citations.enabled=true`.

        Returns:
            text_blocks: list of {"text": str, "citations": [...]} per block
            raw_citations: flat list of all citation dicts
            usage: accumulated token usage
            body_text: concatenated text body
        """
        doc_blocks = _build_citation_docs(documents, cache=cache_documents)

        user_content: list[dict] = [
            *doc_blocks,
            {"type": "text", "text": user_input},
        ]

        body = self._build_request_body(
            model=model,
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            tools=None,
            effort=effort,
            tool_choice=None,
        )
        if extra_tools:
            body["tools"] = list(extra_tools)

        # Citations API needs max_tokens set explicitly (no tool_use).
        body["max_tokens"] = 4_096
        body.pop("tool_choice", None)

        resp_data = await self._post("/v1/messages", body)
        usage = _parse_usage(resp_data)

        text_blocks = []
        raw_citations = []
        body_parts = []
        for block in resp_data.get("content", []):
            if block.get("type") != "text":
                continue
            text = block.get("text", "")
            cits = block.get("citations", [])
            text_blocks.append({"text": text, "citations": cits})
            raw_citations.extend(cits)
            body_parts.append(text)

        return (
            text_blocks,
            raw_citations,
            usage,
            "".join(body_parts),
        )

    # ------------------------------------------------------------------
    # Beta Files API — PDF upload
    # ------------------------------------------------------------------

    async def upload_pdf(
        self, pdf_bytes: bytes, filename: str = "offer.pdf",
    ) -> str:
        """Upload a PDF to Anthropic's Beta Files API. Returns file_id."""
        boundary = "----FormBoundary" + _random_boundary_suffix()

        body_parts = [
            f"--{boundary}",
            f'Content-Disposition: form-data; name="file"; filename="{filename}"',
            "Content-Type: application/pdf",
            "",
        ]
        body_bytes = "\r\n".join(body_parts).encode("utf-8")
        body_bytes += b"\r\n" + pdf_bytes + b"\r\n"
        body_bytes += f"--{boundary}--\r\n".encode("utf-8")

        resp = await self.client.post(
            "/v1/files",
            content=body_bytes,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "anthropic-beta": "files-2024-12-01",
            },
        )

        if resp.status_code != 200:
            raise BackendError(
                f"Files API upload failed (HTTP {resp.status_code}): "
                f"{resp.text[:500]}",
                status_code=resp.status_code,
            )

        data = resp.json()
        file_id = data.get("id")
        if not file_id:
            raise BackendError(
                f"Files API response missing id: {json.dumps(data)[:300]}"
            )
        logger.info("upload_pdf: file_id=%s", file_id)
        return file_id

    # ------------------------------------------------------------------
    # HTTP layer
    # ------------------------------------------------------------------

    def _build_request_body(
        self,
        *,
        model: str,
        system_prompt: str | list[dict],
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        effort: str = "xhigh",
        tool_choice: Optional[dict] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": 4_096,
        }

        # System prompt
        if isinstance(system_prompt, str):
            body["system"] = system_prompt
        else:
            body["system"] = system_prompt

        # Tools
        if tools:
            body["tools"] = tools

        # Adaptive thinking for Opus 4.7+
        if "opus-4-7" in model.lower():
            body["thinking"] = {"type": "adaptive"}
            if effort in {"xhigh", "max"}:
                body["max_tokens"] = 12_000
            else:
                body["max_tokens"] = 8_000

        # Effort
        if effort in _VALID_EFFORTS and "haiku" not in model.lower():
            body["output_config"] = {"effort": effort}

        # Tool choice
        if tool_choice is not None:
            body["tool_choice"] = tool_choice

        return body

    async def _post(self, path: str, body: dict) -> dict:
        try:
            resp = await self.client.post(path, json=body)
        except httpx.TimeoutException:
            raise BackendError("Request timed out", retriable=True)
        except httpx.ConnectError as e:
            raise BackendError(
                f"Connection failed: {e}", retriable=True,
            )

        if resp.status_code >= 500:
            raise BackendError(
                f"Upstream server error (HTTP {resp.status_code}): "
                f"{resp.text[:500]}",
                status_code=resp.status_code,
                retriable=True,
            )

        if resp.status_code in (401, 403):
            raise BackendError(
                f"Authentication failed (HTTP {resp.status_code}). "
                "Check your ANTHROPIC_API_KEY.",
                status_code=resp.status_code,
            )

        if resp.status_code == 429:
            raise BackendError(
                "Rate limited (HTTP 429). Retry after backoff.",
                status_code=429,
                retriable=True,
            )

        if resp.status_code != 200:
            raise BackendError(
                f"Unexpected HTTP {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
            )

        return resp.json()

    def _extract_tool_use_result(self, resp_data: dict) -> LLMCallResult:
        content_blocks = resp_data.get("content", [])
        tool_use = next(
            (b for b in content_blocks if b.get("type") == "tool_use"),
            None,
        )
        if tool_use is None:
            raise BackendError(
                f"Model did not emit a tool_use block. "
                f"stop_reason={resp_data.get('stop_reason')}"
            )

        raw = _unwrap_parameter_value(tool_use.get("input", {}))
        if not isinstance(raw, dict):
            raise BackendError(
                "tool_use.input was not a JSON object."
            )

        return LLMCallResult(raw=raw, usage=_parse_usage(resp_data))

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ---------------------------------------------------------------------------
# Anthropic-specific helpers (sdk-free reimplementations of what the
# anthropic SDK was doing)
# ---------------------------------------------------------------------------


_WRAPPER_KEYS = frozenset({
    "$PARAMETER_VALUE",
    "$PARAMETER_NAME",
    "parameter",
    "parameters",
    "arguments",
    "args",
    "input",
    "value",
})


def _unwrap_parameter_value(raw: Any) -> Any:
    """Unwrap spurious wrapper keys that models add to tool_use.input.

    Same logic as the old `_unwrap_parameter_value` in llm.py —
    models occasionally wrap structured output in synthetic keys.
    """
    if not isinstance(raw, dict):
        return raw

    if len(raw) == 1:
        only_key = next(iter(raw))
        only_val = raw[only_key]
        if only_key in _WRAPPER_KEYS and isinstance(only_val, dict):
            return only_val

    if len(raw) == 2 and "name" in raw and "arguments" in raw:
        args = raw["arguments"]
        if isinstance(args, dict):
            return args

    return raw


def _schema_to_tool(output_schema: type[BaseModel]) -> dict:
    """Wrap a Pydantic schema as an Anthropic tool definition."""
    json_schema = output_schema.model_json_schema()
    return {
        "name": "emit_structured_output",
        "description": (
            f"Emit the final result as a {output_schema.__name__} "
            "JSON object. Do not write anything outside this tool call."
        ),
        "input_schema": json_schema,
    }


def _tool_choice_for(model: str) -> dict:
    """Return tool_choice for the given model.

    Opus 4.7 with adaptive thinking can only use `auto` or `none`.
    Other models can pin the single tool.
    """
    if "opus-4-7" in model.lower():
        return {"type": "auto"}
    return {"type": "tool", "name": "emit_structured_output"}


def _parse_usage(resp_data: dict) -> LLMUsage:
    usage = resp_data.get("usage", {})
    return LLMUsage(
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0) or 0),
        cache_creation_tokens=int(
            usage.get("cache_creation_input_tokens", 0) or 0
        ),
    )


def _accumulate_usage(total: LLMUsage, resp_data: dict) -> LLMUsage:
    u = _parse_usage(resp_data)
    return LLMUsage(
        input_tokens=total.input_tokens + u.input_tokens,
        output_tokens=total.output_tokens + u.output_tokens,
        cache_read_tokens=total.cache_read_tokens + u.cache_read_tokens,
        cache_creation_tokens=total.cache_creation_tokens + u.cache_creation_tokens,
    )


def _random_boundary_suffix() -> str:
    import random
    import string
    return "".join(random.choices(string.ascii_letters + string.digits, k=24))


def _preserve_assistant_blocks(blocks: list[dict]) -> list[dict]:
    """Convert API response content blocks into the shape the API
    expects in `messages[].content` for assistant turns (tool_result
    needs tool_use id preserved)."""
    out = []
    for b in blocks:
        btype = b.get("type")
        if btype == "text":
            out.append({"type": "text", "text": b.get("text", "")})
        elif btype == "tool_use":
            out.append({
                "type": "tool_use",
                "id": b.get("id", ""),
                "name": b.get("name", ""),
                "input": b.get("input", {}),
            })
        elif btype == "thinking":
            out.append({
                "type": "thinking",
                "thinking": b.get("thinking", ""),
                "signature": b.get("signature", ""),
            })
    return out


# ---------------------------------------------------------------------------
# Citations API — document builder (replaces _build_citation_documents)
# ---------------------------------------------------------------------------

_MAX_CACHE_BLOCKS = 4
_MIN_DOC_CHARS_FOR_CACHE = 4_000


def _build_citation_docs(
    documents: list[dict],
    cache: bool = True,
) -> list[dict]:
    """Wrap domain citation documents into Anthropic document blocks."""
    out = []
    for d in documents:
        kind = d.get("type", "text")
        if kind == "text":
            block = {
                "type": "document",
                "source": {
                    "type": "text",
                    "media_type": "text/plain",
                    "data": d["text"],
                },
                "citations": {"enabled": True},
            }
        elif kind == "pdf":
            block = {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": d["data"],
                },
                "citations": {"enabled": True},
            }
        elif kind == "file_id":
            block = {
                "type": "document",
                "source": {"type": "file", "file_id": d["file_id"]},
                "citations": {"enabled": True},
            }
        elif kind == "custom":
            block = {
                "type": "document",
                "source": {
                    "type": "content",
                    "content": [
                        {"type": "text", "text": b["text"]}
                        for b in d["blocks"]
                    ],
                },
                "citations": {"enabled": True},
            }
        else:
            raise ValueError(f"Unknown citation document type: {kind!r}")

        title = d.get("title")
        if title:
            block["title"] = title
        context = d.get("context")
        if context:
            block["context"] = context
        out.append(block)

    if cache:
        size_idx = sorted(
            ((_doc_text_size(orig), i)
             for i, orig in enumerate(documents)
             if _doc_text_size(orig) >= _MIN_DOC_CHARS_FOR_CACHE),
            reverse=True,
        )
        for _, i in size_idx[:_MAX_CACHE_BLOCKS]:
            out[i]["cache_control"] = {"type": "ephemeral"}

    return out


def _doc_text_size(d: dict) -> int:
    if d.get("type") == "text":
        return len(d.get("text", ""))
    if d.get("type") == "custom":
        return sum(len(b.get("text", "")) for b in d.get("blocks", []))
    if d.get("type") in ("pdf", "file_id"):
        return _MIN_DOC_CHARS_FOR_CACHE
    return 0
