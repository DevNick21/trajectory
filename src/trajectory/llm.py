"""Single entry point for all LLM calls.

Every agent in `sub_agents/` goes through `call_agent`. The wrapper:

- Calls Anthropic via the plain Messages API. (Previously this module
  also routed Phase 1 and Phase 4 fan-out agents through a "Managed
  Agents" branch; it attached the beta header to `client.messages.create`
  which was a no-op. Deleted 2026-04-23 — see PROCESS.md Entry 35. The
  genuine Managed Agents integration now lives in
  `src/trajectory/managed/company_investigator.py`.)
- Forces structured output via `tool_use` — the agent is given a single
  tool whose input_schema is the Pydantic JSON schema, and we parse
  `tool_use.input` back into the model. This is the "strict Pydantic
  validated JSON" rule.
- Retries on (a) validation failures and (b) citation-validator rejection,
  feeding the failure back into the prompt. `max_retries=2` by default.
- Logs token usage + USD cost to `storage.log_llm_cost`.
- Refuses non-CRITICAL calls when remaining credits drop below
  `credits_warn_threshold_usd`.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, Optional, TypeVar

from pydantic import BaseModel, ValidationError

from .config import settings
from .storage import log_llm_cost, total_cost_usd

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class CreditBudgetExceeded(RuntimeError):
    """Raised when a non-CRITICAL call is refused due to low remaining credits."""


class AgentCallFailed(RuntimeError):
    """Raised when an agent fails to produce valid output after retries."""


Priority = Literal["CRITICAL", "NORMAL"]
_EFFORT_LEVELS = {"low", "medium", "high", "xhigh"}


# ---------------------------------------------------------------------------
# Client initialisation (lazy — so import stays cheap)
# ---------------------------------------------------------------------------


_anthropic_client = None


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        from anthropic import AsyncAnthropic

        _anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_messages(user_input: str | list[dict]) -> list[dict]:
    if isinstance(user_input, str):
        return [{"role": "user", "content": user_input}]
    return list(user_input)


def _schema_to_tool(output_schema: type[BaseModel]) -> dict:
    """Wrap the Pydantic schema as an Anthropic tool definition.

    The model is forced to emit through this tool; we read `tool_use.input`.
    """
    json_schema = output_schema.model_json_schema()
    return {
        "name": "emit_structured_output",
        "description": (
            f"Emit the final result as a {output_schema.__name__} "
            "JSON object. Do not write anything outside this tool call."
        ),
        "input_schema": json_schema,
    }


def _format_retry_feedback(previous_output: Any, feedback: str) -> str:
    return (
        "Your previous attempt was rejected. Here is what you produced:\n\n"
        f"```\n{json.dumps(previous_output, default=str, indent=2)}\n```\n\n"
        "Rejection reason(s):\n"
        f"{feedback}\n\n"
        "Produce a corrected output. Emit only via the tool."
    )


# Anthropic cache_control requires a minimum prefix size for a block to
# be cacheable. The threshold (~1024 tokens) is enforced server-side —
# under it, the cache_control is ignored silently. We use a character
# proxy (~4 chars/token → 4000 chars = ~1000 tokens) to skip the
# annotation where it would be a no-op, keeping small system prompts
# and chitchat-sized user messages unwrapped.
_CACHE_MIN_CHARS = 4000


def _maybe_wrap_system_for_cache(
    system_prompt: str | list[dict],
) -> str | list[dict]:
    """Attach cache_control to large static system prompts.

    B2: big prompts (verdict, self-audit, Phase 4 generators) are ~5-15k
    tokens and re-sent unchanged on every retry. cache_control on the
    system block makes retry rounds ~10x cheaper on the prefix.

    Idempotent — if the caller already built a list[dict] with explicit
    cache_control, we leave it alone.
    """
    if not settings.enable_prompt_caching:
        return system_prompt
    if not isinstance(system_prompt, str):
        return system_prompt
    if len(system_prompt) < _CACHE_MIN_CHARS:
        return system_prompt
    return [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _maybe_wrap_messages_for_cache(messages: list[dict]) -> list[dict]:
    """Attach cache_control to the first large user message.

    Shape: the first message usually carries the research bundle
    (Phase 2 verdict) or the full prompt payload (Phase 4 generators).
    If that block is large, wrap ONE cache_control breakpoint on it so
    the prompt prefix stays cacheable across the retry loop.

    Later messages (retry feedback etc.) are not wrapped — they're the
    variable part of the prompt and caching them defeats the point.
    """
    if not settings.enable_prompt_caching:
        return messages
    if not messages:
        return messages
    first = messages[0]
    if first.get("role") != "user":
        return messages
    content = first.get("content")
    # Only touch the simple str-content shape; if the caller already
    # built a list-of-blocks (tool_result etc.) leave it alone.
    if not isinstance(content, str):
        return messages
    if len(content) < _CACHE_MIN_CHARS:
        return messages
    wrapped = list(messages)
    wrapped[0] = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": content,
                "cache_control": {"type": "ephemeral"},
            }
        ],
    }
    return wrapped


# ---------------------------------------------------------------------------
# Core call
# ---------------------------------------------------------------------------


async def call_agent(
    agent_name: str,
    system_prompt: str,
    user_input: str | list[dict],
    output_schema: type[T],
    model: Optional[str] = None,
    effort: str = "xhigh",
    max_retries: int = 2,
    session_id: Optional[str] = None,
    priority: Priority = "NORMAL",
    post_validate: Optional[Callable[[T], list[str]]] = None,
) -> T:
    """Universal agent call.

    Args:
        agent_name: Used for routing (Managed Agents vs plain) and cost logs.
        system_prompt: Full system prompt — usually copied from AGENTS.md.
        user_input: User message or pre-built message list.
        output_schema: Pydantic model class. The agent is forced to return this.
        model: Override model. Defaults to Opus 4.7 per CLAUDE.md Rule 7.
        effort: Reasoning effort. `xhigh` for quality-critical agents.
        max_retries: Regeneration attempts after validation or post-validation failure.
        session_id: Threaded into cost log for per-session attribution.
        priority: CRITICAL calls bypass the credit-budget refusal.
        post_validate: Optional callback run on the parsed output. Returns a list
            of failure reasons; empty = accept. Used for citation validation etc.
    """
    if effort not in _EFFORT_LEVELS:
        raise ValueError(f"Unknown effort level: {effort}")

    model = model or settings.opus_model_id

    await _enforce_credit_budget(priority)

    last_feedback: Optional[str] = None
    last_output_for_feedback: Any = None
    call_start = time.perf_counter()

    for attempt in range(max_retries + 1):
        messages = _build_messages(user_input)
        if last_feedback is not None:
            messages.append(
                {
                    "role": "user",
                    "content": _format_retry_feedback(
                        last_output_for_feedback, last_feedback
                    ),
                }
            )

        (
            raw_output,
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_creation_tokens,
        ) = await _call_via_messages_api(
            agent_name=agent_name,
            system_prompt=_maybe_wrap_system_for_cache(system_prompt),
            messages=_maybe_wrap_messages_for_cache(messages),
            output_schema=output_schema,
            model=model,
            effort=effort,
        )

        await log_llm_cost(
            session_id=session_id,
            agent_name=agent_name,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )

        # Parse + validate.
        try:
            parsed = output_schema.model_validate(raw_output)
        except ValidationError as ve:
            last_output_for_feedback = raw_output
            last_feedback = (
                f"Output failed Pydantic validation for {output_schema.__name__}.\n"
                f"{ve}"
            )
            logger.info(
                "Agent %s attempt %d: schema validation failed — retrying.",
                agent_name,
                attempt,
            )
            continue

        # Post-validation hook (e.g. citation validator).
        if post_validate is not None:
            failures = post_validate(parsed)
            if failures:
                last_output_for_feedback = raw_output
                last_feedback = (
                    "Post-validation rejected the output:\n- "
                    + "\n- ".join(failures)
                )
                logger.info(
                    "Agent %s attempt %d: post-validation failed — retrying.",
                    agent_name,
                    attempt,
                )
                continue

        # D2: per-agent timing + token stats. INFO so it's on in
        # production but without the verbosity of DEBUG.
        logger.info(
            "agent=%s model=%s effort=%s duration_ms=%d attempts=%d "
            "input_tokens=%d output_tokens=%d "
            "cache_read_tokens=%d cache_creation_tokens=%d",
            agent_name,
            model,
            effort,
            int((time.perf_counter() - call_start) * 1000),
            attempt + 1,
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_creation_tokens,
        )
        return parsed

    raise AgentCallFailed(
        f"Agent {agent_name} failed after {max_retries + 1} attempts. "
        f"Last feedback: {last_feedback}"
    )


# ---------------------------------------------------------------------------
# Backend: plain Messages API
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Per-model API shape (Anthropic deprecated `thinking.type=enabled` for Opus
# 4.7 in favour of adaptive thinking + `output_config.effort`).
#
# Source: https://platform.claude.com/docs/en/build-with-claude/extended-thinking
#         https://platform.claude.com/docs/en/build-with-claude/effort
#
# Rules captured here so both the Messages API and Managed Agents call paths
# stay in sync:
#   - Opus 4.7+ requires `thinking={"type": "adaptive"}`. The legacy
#     `enabled`/`budget_tokens` shape returns HTTP 400.
#   - Effort is a top-level `output_config={"effort": <level>}` field.
#     Accepted values: low | medium | high | xhigh | max.
#   - When adaptive thinking is active, `tool_choice` may only be
#     `{"type": "auto"}` or `{"type": "none"}` — pinning a single tool
#     errors out. Older Sonnet models without thinking can still pin.
#   - max_tokens needs headroom for thinking + output. Docs recommend
#     ~64k for Opus 4.7 xhigh; we dial it down for cheaper effort levels.
# ---------------------------------------------------------------------------


_VALID_API_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


def _is_opus_47(model: str) -> bool:
    return "opus-4-7" in model.lower()


def _build_messages_request(
    *,
    tool: dict,
    model: str,
    effort: str,
) -> dict[str, Any]:
    """Build the model-specific kwargs dict shared by both call paths."""
    is_opus47 = _is_opus_47(model)
    extra: dict[str, Any] = {}

    # Adaptive thinking is mandatory on Opus 4.7+; harmless to omit on
    # older models that handle it via defaults.
    if is_opus47:
        extra["thinking"] = {"type": "adaptive"}

    # Pass effort through verbatim if it's a known API value.
    if effort in _VALID_API_EFFORTS:
        extra["output_config"] = {"effort": effort}

    # max_tokens — sized to give adaptive thinking room while staying
    # below the SDK's non-streaming threshold. The Anthropic Python SDK
    # raises ValueError("Streaming is required for operations that may
    # take longer than 10 minutes") above ~16k for Opus 4.7. Our outputs
    # are single tool_use blocks (CV, Verdict, etc.) — typical ~2-4k
    # output tokens — so 12k is plenty of headroom for thinking + output
    # without forcing us onto the streaming API.
    if is_opus47 and effort in {"xhigh", "max"}:
        extra["max_tokens"] = 12_000
    elif is_opus47:
        extra["max_tokens"] = 8_000
    else:
        extra["max_tokens"] = 4_096

    # tool_choice — adaptive thinking forbids forced-tool. Only pin the
    # single tool when no thinking block is sent (i.e. older Sonnet).
    if is_opus47:
        extra["tool_choice"] = {"type": "auto"}
    else:
        extra["tool_choice"] = {"type": "tool", "name": tool["name"]}

    return extra


async def _call_via_messages_api(
    *,
    agent_name: str,
    system_prompt: str | list[dict],
    messages: list[dict],
    output_schema: type[BaseModel],
    model: str,
    effort: str,
) -> tuple[dict, int, int, int, int]:
    """Returns (parsed-json-dict, input_tokens, output_tokens,
    cache_read_tokens, cache_creation_tokens).

    Cache token counts default to 0 when the API response doesn't
    include them (pre-caching SDK versions or caching disabled).
    """
    client = _get_anthropic_client()
    tool = _schema_to_tool(output_schema)

    request_kwargs = _build_messages_request(
        tool=tool, model=model, effort=effort,
    )

    resp = await client.messages.create(
        model=model,
        system=system_prompt,
        messages=messages,
        tools=[tool],
        **request_kwargs,
    )

    tool_use_block = next(
        (b for b in resp.content if getattr(b, "type", None) == "tool_use"),
        None,
    )
    if tool_use_block is None:
        raise AgentCallFailed(
            f"Agent {agent_name} did not emit tool_use block. "
            f"stop_reason={resp.stop_reason}"
        )

    raw = _unwrap_parameter_value(tool_use_block.input)
    if not isinstance(raw, dict):
        raise AgentCallFailed(
            f"Agent {agent_name} tool_use.input was not a JSON object."
        )

    usage = resp.usage
    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cache_creation = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    return (
        raw,
        int(usage.input_tokens),
        int(usage.output_tokens),
        cache_read,
        cache_creation,
    )


_WRAPPER_KEYS = frozenset({
    "$PARAMETER_VALUE",
    "$PARAMETER_NAME",  # observed from Opus 4.7 on the verdict schema
    "parameter",
    "parameters",
    "arguments",
    "args",
    "input",
    "value",
})


def _unwrap_parameter_value(raw: Any) -> Any:
    """Unwrap the spurious wrapper key Anthropic occasionally adds to
    tool_use input on complex schemas.

    Observed wrappers from Opus 4.7 in the wild (2026-04, complex
    Pydantic schemas with discriminated unions or 5+ required fields):
      - `{"$PARAMETER_VALUE": {...real fields...}}`            (1-key)
      - `{"$PARAMETER_NAME":  {...real fields...}}`            (1-key)
      - `{"parameter":        {...real fields...}}`            (1-key)
      - `{"parameters":       {...real fields...}}`            (1-key)
      - `{"arguments":        {...real fields...}}`            (1-key)
      - `{"name": "CVOutput", "arguments": {...real fields...}}` (2-key
         function-call envelope; observed on the cv_tailor schema in
         PROCESS Entry 46's full live run — Pydantic complained
         "5 validation errors for CVOutput / contact, professional_summary,
         experience, education, skills" because it tried to validate
         the envelope itself instead of its `arguments` payload)

    Same root cause across all variants: the model is uncertain about
    the schema shape and nests the args inside a synthetic key. Pydantic
    then rejects the wrapped object because none of the schema's
    required fields are at the top level. Stripping any single-key
    wrapper whose value is a dict — or a 2-key `{name, arguments}`
    envelope — resolves this transparently; without the unwrap the
    retry loop would burn attempts on a purely encoding-level quirk.

    REMOVE WHEN: Anthropic publishes a model release where the smoke
    suite passes for ≥10 consecutive runs without any
    `_unwrap_parameter_value` actually doing work (i.e. log this
    function's "I had to unwrap" rate and watch it go to zero).
    The current Opus 4.7 still trips this on the verdict + cv_tailor
    schemas; safe to delete only after a clean window.
    """
    if not isinstance(raw, dict):
        return raw

    # Single-key wrapper.
    if len(raw) == 1:
        only_key = next(iter(raw))
        only_val = raw[only_key]
        if only_key in _WRAPPER_KEYS and isinstance(only_val, dict):
            return only_val

    # Two-key function-call envelope: `{"name": "<schema>", "arguments": {...}}`.
    # The model occasionally emits this when it confuses tool_use input
    # with a function-call payload. We accept either ordering and any
    # `name` value as long as `arguments` is a dict.
    if len(raw) == 2 and "name" in raw and "arguments" in raw:
        args = raw["arguments"]
        if isinstance(args, dict):
            return args

    return raw


# ---------------------------------------------------------------------------
# Multi-turn tool-use loop (agentic CV tailor; see PROCESS.md Entry 36)
# ---------------------------------------------------------------------------


async def call_agent_with_tools(
    *,
    agent_name: str,
    system_prompt: str,
    user_input: str,
    tools: list[dict],
    tool_executor: Callable[[str, dict], Awaitable[str]],
    response_schema: type[T],
    model: str,
    effort: str = "xhigh",
    session_id: Optional[str] = None,
    max_iterations: int = 10,
    priority: Priority = "NORMAL",
) -> T:
    """Run a multi-turn tool-use loop until the model emits structured output.

    The agent has two ways to respond on each turn:
      1. Call one of the provided tools (`tool_use` content block) — the
         executor runs it, we append a `tool_result` block, loop.
      2. Emit final structured output via the synthetic
         `emit_structured_output` tool (the same shape as `call_agent`
         uses). We parse, validate, return.

    `tool_executor(tool_name, tool_input)` returns the tool result as a
    string (already shielded by the caller if appropriate).

    Token usage accumulates across turns; logged once at the end.
    `max_iterations` ceiling prevents runaway loops; exceeding raises
    `AgentCallFailed`.
    """
    if effort not in _EFFORT_LEVELS:
        raise ValueError(f"Unknown effort level: {effort}")

    await _enforce_credit_budget(priority)

    client = _get_anthropic_client()
    final_tool = _schema_to_tool(response_schema)
    final_tool_name = final_tool["name"]
    all_tools = list(tools) + [final_tool]

    request_kwargs = _build_messages_request(
        tool=final_tool, model=model, effort=effort,
    )
    # The multi-turn loop needs `auto` tool_choice every turn so the
    # model can pick between user tools and the final emitter. Override
    # whatever _build_messages_request set.
    request_kwargs["tool_choice"] = {"type": "auto"}

    messages: list[dict] = [{"role": "user", "content": user_input}]
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_creation = 0

    # Apply cache_control breakpoints to the static prefix. The
    # multi-turn loop only mutates the tail of `messages`, so wrapping
    # the first user turn here is safe across all iterations.
    cached_system = _maybe_wrap_system_for_cache(system_prompt)

    for turn in range(max_iterations):
        # On each turn re-wrap in case the loop appended new tool_result
        # blocks; wrapping is idempotent on the prefix.
        wrapped_messages = _maybe_wrap_messages_for_cache(messages)
        resp = await client.messages.create(
            model=model,
            system=cached_system,
            messages=wrapped_messages,
            tools=all_tools,
            **request_kwargs,
        )

        usage = resp.usage
        total_input += int(getattr(usage, "input_tokens", 0))
        total_output += int(getattr(usage, "output_tokens", 0))
        total_cache_read += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        total_cache_creation += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)

        # Append the assistant response to the message list verbatim — we
        # need both text/thinking blocks AND tool_use blocks because the
        # API requires every tool_use to be followed by a tool_result on
        # the next turn.
        assistant_blocks = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                assistant_blocks.append(
                    {"type": "text", "text": getattr(block, "text", "")}
                )
            elif btype == "tool_use":
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": getattr(block, "id", ""),
                        "name": getattr(block, "name", ""),
                        "input": getattr(block, "input", {}),
                    }
                )
            elif btype == "thinking":
                # Preserve thinking blocks so adaptive thinking continues
                # to work across turns.
                assistant_blocks.append(
                    {
                        "type": "thinking",
                        "thinking": getattr(block, "thinking", ""),
                        "signature": getattr(block, "signature", ""),
                    }
                )
        messages.append({"role": "assistant", "content": assistant_blocks})

        # Find every tool_use in this turn — there can be multiple.
        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]

        # If the model emitted the final tool, we're done.
        final_call = next(
            (tu for tu in tool_uses if getattr(tu, "name", "") == final_tool_name),
            None,
        )
        if final_call is not None:
            raw = _unwrap_parameter_value(getattr(final_call, "input", {}))
            if not isinstance(raw, dict):
                raise AgentCallFailed(
                    f"Agent {agent_name} final tool_use.input was not a JSON object."
                )
            await log_llm_cost(
                session_id=session_id,
                agent_name=agent_name,
                model=model,
                input_tokens=total_input,
                output_tokens=total_output,
                cache_read_tokens=total_cache_read,
                cache_creation_tokens=total_cache_creation,
            )
            return response_schema.model_validate(raw)

        # Otherwise, execute every non-final tool the model called and
        # append all results in one user message.
        if not tool_uses:
            # Model returned text-only — give it a single nudge to use a
            # tool or emit final.
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You produced a text-only response. Please either "
                        f"call one of the provided tools or emit the final "
                        f"{response_schema.__name__} via the "
                        f"`{final_tool_name}` tool. Don't reply with "
                        "free-form text."
                    ),
                }
            )
            continue

        result_blocks: list[dict] = []
        for tu in tool_uses:
            tool_name = getattr(tu, "name", "")
            tool_use_id = getattr(tu, "id", "")
            tool_input = getattr(tu, "input", {}) or {}
            try:
                tool_result = await tool_executor(tool_name, tool_input)
            except Exception as exc:
                logger.warning(
                    "Tool %s raised in agent %s: %r", tool_name, agent_name, exc,
                )
                tool_result = f"ERROR: tool {tool_name} failed: {exc}"
            result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": tool_result,
                }
            )
        messages.append({"role": "user", "content": result_blocks})

    # Loop exhausted without final emission.
    await log_llm_cost(
        session_id=session_id,
        agent_name=agent_name,
        model=model,
        input_tokens=total_input,
        output_tokens=total_output,
        cache_read_tokens=total_cache_read,
        cache_creation_tokens=total_cache_creation,
    )
    raise AgentCallFailed(
        f"Agent {agent_name} exceeded max_iterations={max_iterations} "
        f"without emitting final {response_schema.__name__}."
    )


# ---------------------------------------------------------------------------
# Streaming (onboarding UX)
# ---------------------------------------------------------------------------


async def stream_agent(
    agent_name: str,
    system_prompt: str,
    user_input: str | list[dict],
    model: Optional[str] = None,
    session_id: Optional[str] = None,
    priority: Priority = "NORMAL",
) -> AsyncIterator[str]:
    """Unstructured streaming — used only where UX needs token-by-token output
    (onboarding follow-ups). Does not enforce structured schema."""
    await _enforce_credit_budget(priority)
    model = model or settings.sonnet_model_id
    client = _get_anthropic_client()
    input_tokens = output_tokens = 0
    cache_read_tokens = cache_creation_tokens = 0

    async with client.messages.stream(
        model=model,
        max_tokens=1024,
        system=_maybe_wrap_system_for_cache(system_prompt),
        messages=_maybe_wrap_messages_for_cache(_build_messages(user_input)),
    ) as stream:
        async for text in stream.text_stream:
            yield text
        final = await stream.get_final_message()
        input_tokens = final.usage.input_tokens
        output_tokens = final.usage.output_tokens
        cache_read_tokens = int(
            getattr(final.usage, "cache_read_input_tokens", 0) or 0
        )
        cache_creation_tokens = int(
            getattr(final.usage, "cache_creation_input_tokens", 0) or 0
        )

    await log_llm_cost(
        session_id=session_id,
        agent_name=agent_name,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
    )


# ---------------------------------------------------------------------------
# Credit budget guard
# ---------------------------------------------------------------------------


async def _enforce_credit_budget(priority: Priority) -> None:
    spent = await total_cost_usd()
    remaining = settings.credits_budget_usd - spent
    if remaining < settings.credits_warn_threshold_usd and priority != "CRITICAL":
        raise CreditBudgetExceeded(
            f"Remaining credits ${remaining:.2f} below threshold "
            f"${settings.credits_warn_threshold_usd:.2f}. "
            "Non-CRITICAL calls are refused. Set priority=CRITICAL to override."
        )
    if remaining < settings.credits_warn_threshold_usd:
        logger.warning(
            "CRITICAL call proceeding under low-credit state: remaining=$%.2f",
            remaining,
        )
# ===========================================================================
# Adapter dispatch (post-2026-04-25 migration; see CLAUDE.md "Adapter
# dispatch in llm.py" + PROCESS.md Entry 43).
#
# Four named adapters - every new agent picks exactly one. The original
# `call_agent` stays as a backwards-compat alias of `call_structured` so
# existing call sites keep working through the migration.
# ===========================================================================


from dataclasses import dataclass


# --- (1) call_structured ---------------------------------------------------
# Schema-dense path. Same behaviour as `call_agent`.

call_structured = call_agent


# --- (2) call_with_citations ----------------------------------------------
# Source-grounded path using Anthropic's first-party Citations API. The
# agent emits a free-form text body (no tool_use envelope - Citations is
# incompatible with output_config.format), and each text block carries a
# list of `cited_text` annotations the SDK guarantees are verbatim
# substrings of the supplied documents.


@dataclass
class CitationResult:
    """Output of `call_with_citations`.

    `body` is the concatenated free-form text. `text_blocks` preserves
    the per-block split so callers can do paragraph-level grouping.

    `raw_citations` is a flat list of every citation annotation in the
    response. Workstream B will provide `Citation.from_api(raw)` to
    project these into our domain `schemas.Citation` discriminator.
    """

    body: str
    text_blocks: list[dict]
    raw_citations: list[dict]
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


_MAX_CACHE_CONTROL_BLOCKS = 4
_MIN_DOC_CHARS_FOR_CACHE = 4_000


def _build_citation_documents(
    documents: list[dict],
    cache_documents: bool = True,
) -> list[dict]:
    """Wrap caller-provided documents with citations.enabled=True.

    Anthropic limits a single request to 4 cache_control breakpoints.
    We only attach cache_control to the largest documents (>~1k tokens
    each), and at most 4 of them. Smaller docs (one-line gov_data
    fields, short career entries) cache poorly anyway since the
    minimum cacheable prefix is ~1024 tokens.

    Each input dict can be:
      - {"type": "text", "text": "...", "title": "...", "context": "..."}
      - {"type": "pdf", "data": "<base64>", "title": "..."}
      - {"type": "file_id", "file_id": "...", "title": "..."}
      - {"type": "custom", "blocks": [{"text": "..."}, ...], "title": "..."}
    """
    out: list[dict] = []
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

    # Apply cache_control to up to 4 of the LARGEST documents that
    # exceed the ~1024-token cacheable threshold. This avoids the
    # 400 "A maximum of 4 blocks with cache_control may be provided"
    # error when many small docs (gov_data fields, career entries)
    # are bundled with a couple of big scraped pages.
    if cache_documents and settings.enable_prompt_caching:
        size_idx_pairs: list[tuple[int, int]] = []
        for i, (orig, block) in enumerate(zip(documents, out)):
            size = _document_text_size(orig)
            if size >= _MIN_DOC_CHARS_FOR_CACHE:
                size_idx_pairs.append((size, i))
        size_idx_pairs.sort(reverse=True)
        for _, i in size_idx_pairs[:_MAX_CACHE_CONTROL_BLOCKS]:
            out[i]["cache_control"] = {"type": "ephemeral"}
    return out


def _document_text_size(d: dict) -> int:
    """Approximate character count of a citation-document input
    (used to decide whether cache_control is worth attaching)."""
    if d.get("type") == "text":
        return len(d.get("text", ""))
    if d.get("type") == "custom":
        return sum(len(b.get("text", "")) for b in d.get("blocks", []))
    if d.get("type") in ("pdf", "file_id"):
        # Treat PDFs as worth caching — exact size unknown but they
        # clear the threshold by definition.
        return _MIN_DOC_CHARS_FOR_CACHE
    return 0


async def call_with_citations(
    agent_name: str,
    system_prompt: str,
    user_input: str,
    documents: list[dict],
    *,
    model: Optional[str] = None,
    effort: str = "xhigh",
    session_id: Optional[str] = None,
    priority: Priority = "NORMAL",
    cache_documents: bool = True,
    extra_tools: Optional[list[dict]] = None,
    max_retries: int = 0,
    post_validate: Optional[Callable[[CitationResult], list[str]]] = None,
) -> CitationResult:
    """Citations-API call.

    Returns a CitationResult. The agent author projects body +
    raw_citations into their domain schema (Workstream B).

    `post_validate` mirrors `call_agent`: when provided and `max_retries > 0`,
    a returning a non-empty list of failure reasons appends a feedback turn
    and regenerates. The supplied documents stay cache-hot across retries so
    the regen cost is dominated by output tokens, not the bundle prefix.
    """
    if effort not in _EFFORT_LEVELS:
        raise ValueError(f"Unknown effort level: {effort}")
    model = model or settings.opus_model_id
    await _enforce_credit_budget(priority)

    client = _get_anthropic_client()
    call_start = time.perf_counter()

    doc_blocks = _build_citation_documents(documents, cache_documents=cache_documents)

    is_opus47 = _is_opus_47(model)
    request_kwargs: dict[str, Any] = {}
    if is_opus47:
        request_kwargs["thinking"] = {"type": "adaptive"}
    if effort in _VALID_API_EFFORTS:
        request_kwargs["output_config"] = {"effort": effort}
    if is_opus47 and effort in {"xhigh", "max"}:
        request_kwargs["max_tokens"] = 12_000
    elif is_opus47:
        request_kwargs["max_tokens"] = 8_000
    else:
        request_kwargs["max_tokens"] = 4_096
    if extra_tools:
        request_kwargs["tools"] = list(extra_tools)

    last_feedback: Optional[str] = None
    last_body: Optional[str] = None
    total_input = total_output = total_cache_read = total_cache_creation = 0
    blocks_count = citations_count = 0

    last_result: Optional[CitationResult] = None

    for attempt in range(max_retries + 1):
        user_content: list[dict] = [
            *doc_blocks,
            {"type": "text", "text": user_input},
        ]
        if last_feedback is not None:
            user_content.append(
                {
                    "type": "text",
                    "text": (
                        "Your previous attempt was rejected. Here is what you "
                        f"produced:\n\n```\n{last_body}\n```\n\n"
                        "Rejection reason(s):\n"
                        f"{last_feedback}\n\n"
                        "Produce a corrected output now. Same format and the "
                        "same citation discipline — but address every rejection "
                        "above. Do not repeat the rejected wording."
                    ),
                }
            )

        resp = await client.messages.create(
            model=model,
            system=_maybe_wrap_system_for_cache(system_prompt),
            messages=[{"role": "user", "content": user_content}],
            **request_kwargs,
        )

        text_blocks: list[dict] = []
        raw_citations: list[dict] = []
        body_parts: list[str] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype != "text":
                continue
            text = getattr(block, "text", "")
            cits = getattr(block, "citations", None) or []
            cit_dicts: list[dict] = []
            for c in cits:
                if hasattr(c, "model_dump"):
                    cit_dicts.append(c.model_dump())
                elif isinstance(c, dict):
                    cit_dicts.append(dict(c))
                else:
                    cit_dicts.append(
                        {k: getattr(c, k) for k in dir(c) if not k.startswith("_")}
                    )
            text_blocks.append({"text": text, "citations": cit_dicts})
            raw_citations.extend(cit_dicts)
            body_parts.append(text)

        usage = resp.usage
        input_tokens = int(usage.input_tokens)
        output_tokens = int(usage.output_tokens)
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_creation = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        total_input += input_tokens
        total_output += output_tokens
        total_cache_read += cache_read
        total_cache_creation += cache_creation
        blocks_count = len(text_blocks)
        citations_count = len(raw_citations)

        result = CitationResult(
            body="".join(body_parts),
            text_blocks=text_blocks,
            raw_citations=raw_citations,
            input_tokens=total_input,
            output_tokens=total_output,
            cache_read_tokens=total_cache_read,
            cache_creation_tokens=total_cache_creation,
        )
        last_result = result

        if post_validate is not None:
            failures = post_validate(result)
            if failures:
                last_body = result.body
                last_feedback = "- " + "\n- ".join(failures)
                logger.info(
                    "Agent %s attempt %d: post-validation failed — retrying.",
                    agent_name,
                    attempt,
                )
                continue

        await log_llm_cost(
            session_id=session_id,
            agent_name=agent_name,
            model=model,
            input_tokens=total_input,
            output_tokens=total_output,
            cache_read_tokens=total_cache_read,
            cache_creation_tokens=total_cache_creation,
        )

        logger.info(
            "agent=%s adapter=citations model=%s effort=%s duration_ms=%d "
            "attempts=%d blocks=%d citations=%d input_tokens=%d "
            "output_tokens=%d cache_read=%d cache_creation=%d",
            agent_name,
            model,
            effort,
            int((time.perf_counter() - call_start) * 1000),
            attempt + 1,
            blocks_count,
            citations_count,
            total_input,
            total_output,
            total_cache_read,
            total_cache_creation,
        )
        return result

    # Retry budget exhausted — log accumulated cost, then raise.
    await log_llm_cost(
        session_id=session_id,
        agent_name=agent_name,
        model=model,
        input_tokens=total_input,
        output_tokens=total_output,
        cache_read_tokens=total_cache_read,
        cache_creation_tokens=total_cache_creation,
    )
    raise AgentCallFailed(
        f"Agent {agent_name} (citations) failed after {max_retries + 1} "
        f"attempts. Last feedback:\n{last_feedback}"
    )


# --- (3) call_with_tools - server-side tool support ----------------------
# Thin upgrade over `call_agent` that also accepts Anthropic server-side
# tools (web_search, web_fetch, code_execution) alongside the structured-
# output emit_structured_output tool.


async def call_with_tools(
    agent_name: str,
    system_prompt: str,
    user_input: str,
    output_schema: type[T],
    server_tools: list[dict],
    *,
    model: Optional[str] = None,
    effort: str = "xhigh",
    max_retries: int = 2,
    session_id: Optional[str] = None,
    priority: Priority = "NORMAL",
    post_validate: Optional[Callable[[T], list[str]]] = None,
) -> T:
    """Schema-dense call WITH server-side tools attached.

    `server_tools` accepts Anthropic server-side tool dicts, e.g.:
      - {"type": "web_search_20260209", "name": "web_search"}
      - {"type": "web_fetch_20260209", "name": "web_fetch"}
      - {"type": "code_execution_20260209", "name": "code_execution"}

    The platform executes server tools server-side; the model still
    must call `emit_structured_output` once with the final answer.
    """
    if effort not in _EFFORT_LEVELS:
        raise ValueError(f"Unknown effort level: {effort}")
    model = model or settings.opus_model_id
    await _enforce_credit_budget(priority)

    client = _get_anthropic_client()
    output_tool = _schema_to_tool(output_schema)
    all_tools = [output_tool, *server_tools]

    last_feedback: Optional[str] = None
    last_output_for_feedback: Any = None
    call_start = time.perf_counter()

    is_opus47 = _is_opus_47(model)
    base_request: dict[str, Any] = {}
    if is_opus47:
        base_request["thinking"] = {"type": "adaptive"}
    if effort in _VALID_API_EFFORTS:
        base_request["output_config"] = {"effort": effort}
    if is_opus47 and effort in {"xhigh", "max"}:
        base_request["max_tokens"] = 12_000
    elif is_opus47:
        base_request["max_tokens"] = 8_000
    else:
        base_request["max_tokens"] = 4_096
    base_request["tool_choice"] = {"type": "auto"}

    for attempt in range(max_retries + 1):
        messages = _build_messages(user_input)
        if last_feedback is not None:
            messages.append({
                "role": "user",
                "content": _format_retry_feedback(
                    last_output_for_feedback, last_feedback
                ),
            })

        agg_input = agg_output = agg_cache_read = agg_cache_creation = 0
        raw_output: Optional[dict] = None
        for _ in range(8):  # bounded inner loop
            resp = await client.messages.create(
                model=model,
                system=_maybe_wrap_system_for_cache(system_prompt),
                messages=_maybe_wrap_messages_for_cache(messages),
                tools=all_tools,
                **base_request,
            )
            usage = resp.usage
            agg_input += int(usage.input_tokens)
            agg_output += int(usage.output_tokens)
            agg_cache_read += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
            agg_cache_creation += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)

            emit = next(
                (b for b in resp.content
                 if getattr(b, "type", None) == "tool_use"
                 and getattr(b, "name", "") == "emit_structured_output"),
                None,
            )
            if emit is not None:
                raw_output = _unwrap_parameter_value(emit.input)
                break

            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason in {"end_turn", "stop_sequence"}:
                break

        await log_llm_cost(
            session_id=session_id,
            agent_name=agent_name,
            model=model,
            input_tokens=agg_input,
            output_tokens=agg_output,
            cache_read_tokens=agg_cache_read,
            cache_creation_tokens=agg_cache_creation,
        )

        if raw_output is None:
            last_output_for_feedback = None
            last_feedback = (
                "Agent did not emit the structured output tool. "
                "It must call `emit_structured_output` exactly once."
            )
            continue
        if not isinstance(raw_output, dict):
            last_output_for_feedback = raw_output
            last_feedback = "tool_use.input was not a JSON object."
            continue

        try:
            parsed = output_schema.model_validate(raw_output)
        except ValidationError as ve:
            last_output_for_feedback = raw_output
            last_feedback = (
                f"Output failed Pydantic validation for {output_schema.__name__}.\n"
                f"{ve}"
            )
            continue

        if post_validate is not None:
            failures = post_validate(parsed)
            if failures:
                last_output_for_feedback = raw_output
                last_feedback = (
                    "Post-validation rejected the output:\n- "
                    + "\n- ".join(failures)
                )
                continue

        logger.info(
            "agent=%s adapter=tools model=%s effort=%s duration_ms=%d "
            "attempts=%d input_tokens=%d output_tokens=%d "
            "cache_read=%d cache_creation=%d server_tools=%s",
            agent_name,
            model,
            effort,
            int((time.perf_counter() - call_start) * 1000),
            attempt + 1,
            agg_input,
            agg_output,
            agg_cache_read,
            agg_cache_creation,
            [t.get("name") for t in server_tools],
        )
        return parsed

    raise AgentCallFailed(
        f"Agent {agent_name} (with-tools) failed after {max_retries + 1} attempts. "
        f"Last feedback: {last_feedback}"
    )


# --- (4) call_in_session - Managed Agents dispatcher ----------------------


async def call_in_session(agent_name: str, *args, **kwargs):
    """Dispatch to a registered Managed Agents session.

    Concrete sessions (post-migration):
      - "company_investigator" -> managed/company_investigator.py
      - "reviews_investigator" -> managed/reviews_investigator.py
      - "verdict_deep_research" -> managed/verdict_deep_research.py
      - "cv_tailor_advisor" -> managed/cv_tailor_advisor.py
      - "prompt_auditor_empirical" -> managed/prompt_auditor_empirical.py
    """
    from . import managed as _managed

    sessions = getattr(_managed, "SESSIONS", {})
    session = sessions.get(agent_name)
    if session is None:
        raise NotImplementedError(
            f"No managed session registered for agent {agent_name!r}. "
            f"Available: {sorted(sessions)}"
        )
    return await session(*args, **kwargs)


# ---------------------------------------------------------------------------
# Token counting (preflight cost gate)
# ---------------------------------------------------------------------------


async def count_tokens(
    *,
    model: Optional[str] = None,
    system: str | list[dict] | None = None,
    messages: list[dict],
    tools: Optional[list[dict]] = None,
) -> int:
    """Wrapper around `client.messages.count_tokens`.

    Used as a true preflight gate before non-CRITICAL calls - replaces
    the post-hoc `estimate_cost_usd` heuristic. Returns the input-token
    count Anthropic would charge for this exact request.
    """
    client = _get_anthropic_client()
    model = model or settings.opus_model_id
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if system is not None:
        payload["system"] = system
    if tools:
        payload["tools"] = tools
    resp = await client.messages.count_tokens(**payload)
    return int(getattr(resp, "input_tokens", 0))


# ---------------------------------------------------------------------------
# 1-hour cache helper (opt-in for batch runners + bot prefixes)
# ---------------------------------------------------------------------------


def cache_control_block(extended: bool = False) -> dict[str, Any]:
    """Return the right `cache_control` value depending on settings.

    `extended=True` and `settings.enable_1hr_cache_for_batch=True`
    together upgrade to the 1-hour TTL; otherwise stays on the 5-minute
    default.
    """
    if extended and settings.enable_1hr_cache_for_batch:
        return {"type": "ephemeral", "ttl": "1h"}
    return {"type": "ephemeral"}
