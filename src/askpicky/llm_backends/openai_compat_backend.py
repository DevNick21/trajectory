"""OpenAI-compatible backend via httpx.

Works with any provider that exposes an OpenAI-compatible
`/v1/chat/completions` endpoint: OpenAI, DeepSeek, OpenRouter,
Together, Groq, any self-hosted vLLM/Ollama.

Providers that support native `response_format={"type": "json_schema"}`
(OpenAI, Groq) get strict schema enforcement. Providers that only
support `{"type": "json_object"}` (DeepSeek, vLLM, Ollama) fall back
to system-prompt enforcement with a JSON-mode constraint.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx
from pydantic import BaseModel

from .base import BackendError, LLMCallResult, LLMUsage

logger = logging.getLogger(__name__)

class OpenAICompatBackend:
    """Generic backend for any OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.openai.com/v1",
        api_key: str = "",
        timeout: float = 120.0,
        supports_json_schema: bool = True,
    ):
        if not api_key:
            raise BackendError(
                "API key is required for OpenAI-compatible backend. "
                "Set the appropriate env var (OPENAI_API_KEY / DEEPSEEK_API_KEY)."
            )

        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None
        self._timeout = timeout
        self._supports_json_schema = supports_json_schema

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
        return self._client

    async def call(
        self,
        *,
        system_prompt: str | list[dict],
        messages: list[dict],
        output_schema: type[BaseModel],
        model: str,
        effort: str = "xhigh",
        max_tokens: int = 4_096,
        provider: str = "deepseek",
    ) -> LLMCallResult:
        """Send a chat completions request and return parsed JSON + usage."""

        sys_text = _flatten_system_prompt(system_prompt)
        openai_messages = _build_openai_messages(sys_text, messages)

        json_schema = output_schema.model_json_schema()
        schema_name = output_schema.__name__

        body: dict[str, Any] = {
            "model": model,
            "messages": openai_messages,
            "max_tokens": max_tokens,
        }

        if self._supports_json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": json_schema,
                },
            }
        else:
            # JSON mode only — enforce the schema via system prompt.
            body["response_format"] = {"type": "json_object"}
            schema_text = json.dumps(json_schema, indent=2)
            body["messages"][0]["content"] = (
                f"{body['messages'][0]['content']}\n\n"
                f"You MUST respond with a JSON object matching this schema. "
                f"No other text before or after the JSON:\n"
                f"```json\n{schema_text}\n```"
            )

        # Map Anthropic-style `effort` to provider-specific reasoning_effort.
        #
        # DeepSeek: valid values are "high", "max".
        #   low/medium → high, high → high, xhigh/max → max.
        #
        # OpenAI: valid values are "low", "medium", "high", "xhigh".
        #   All pass through except "max" → "xhigh".
        if provider == "openai":
            if effort == "max":
                body["reasoning_effort"] = "xhigh"
            elif effort in {"low", "medium", "high", "xhigh"}:
                body["reasoning_effort"] = effort
            else:
                body["reasoning_effort"] = "medium"
        else:
            # deepseek (default)
            if effort in {"xhigh", "max"}:
                body["reasoning_effort"] = "max"
            else:
                body["reasoning_effort"] = "high"

        try:
            resp = await self.client.post(
                "/chat/completions",
                json=body,
            )
        except httpx.TimeoutException:
            raise BackendError(
                "Request timed out", retriable=True,
            )
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

        if resp.status_code == 401 or resp.status_code == 403:
            raise BackendError(
                f"Authentication failed (HTTP {resp.status_code}). "
                "Check your API key.",
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

        data = resp.json()

        choice = data.get("choices", [{}])[0]
        finish_reason = choice.get("finish_reason", "stop")
        message = choice.get("message", {})
        raw_text = message.get("content") or "{}"

        # Some providers return refusal instead of content
        if not raw_text and message.get("refusal"):
            raise BackendError(
                f"Model refused: {message['refusal'][:300]}"
            )

        if finish_reason == "length":
            raise BackendError(
                f"Model output truncated — max_tokens ({max_tokens}) "
                f"was too low for this response. "
                f"First 300 chars: {raw_text[:300]}",
                retriable=True,
            )

        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError:
            # Attempt truncation recovery: find the outermost balanced {}.
            truncated = _extract_json_object(raw_text)
            if truncated is not None:
                try:
                    raw = json.loads(truncated)
                except json.JSONDecodeError:
                    pass
                else:
                    return self._build_result(raw, data)

            raise BackendError(
                f"Model response was not valid JSON. "
                f"First 300 chars: {raw_text[:300]}"
            )

        if not isinstance(raw, dict):
            raise BackendError(
                f"Model output was not a JSON object "
                f"(got {type(raw).__name__})"
            )

        return self._build_result(raw, data)

    def _build_result(self, raw: dict, data: dict) -> LLMCallResult:
        usage_data = data.get("usage", {})
        return LLMCallResult(
            raw=raw,
            usage=LLMUsage(
                input_tokens=int(usage_data.get("prompt_tokens", 0)),
                output_tokens=int(usage_data.get("completion_tokens", 0)),
            ),
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flatten_system_prompt(system_prompt: str | list[dict]) -> str:
    if isinstance(system_prompt, str):
        return system_prompt
    parts: list[str] = []
    for block in system_prompt:
        if isinstance(block, dict):
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def _build_openai_messages(
    sys_text: str, messages: list[dict]
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    if sys_text:
        result.append({"role": "system", "content": sys_text})
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, str):
            result.append({"role": role, "content": content})
        elif isinstance(content, list):
            text = _flatten_content_blocks(content)
            result.append({"role": role, "content": text})
    return result


def _flatten_content_blocks(blocks: list) -> str:
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict):
            t = block.get("text") or block.get("content") or ""
            if isinstance(t, str):
                parts.append(t)
    return "\n".join(parts)


def _extract_json_object(text: str) -> Optional[str]:
    """Try to extract a balanced outermost JSON object from truncated text."""
    if not text.strip().startswith("{"):
        return None
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[: i + 1]
    return None
