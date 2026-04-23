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

        raw_output, input_tokens, output_tokens = await _call_via_messages_api(
            agent_name=agent_name,
            system_prompt=system_prompt,
            messages=messages,
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
    system_prompt: str,
    messages: list[dict],
    output_schema: type[BaseModel],
    model: str,
    effort: str,
) -> tuple[dict, int, int]:
    """Returns (parsed-json-dict, input_tokens, output_tokens)."""
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
    return raw, int(usage.input_tokens), int(usage.output_tokens)


_WRAPPER_KEYS = frozenset({
    "$PARAMETER_VALUE",
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

    Observed wrappers from Opus 4.7 in the wild:
      - `{"$PARAMETER_VALUE": {...real fields...}}`
      - `{"parameter": {...real fields...}}`

    Same root cause: the model is uncertain about the schema shape and
    nests the args inside a synthetic key. Pydantic then rejects the
    wrapped object because none of the schema's required fields are at
    the top level. Stripping any single-key wrapper whose value is a
    dict resolves this transparently — without it the retry loop would
    burn attempts on a purely encoding-level quirk.
    """
    if (
        isinstance(raw, dict)
        and len(raw) == 1
        and isinstance(next(iter(raw.values())), dict)
    ):
        only_key = next(iter(raw))
        if only_key in _WRAPPER_KEYS:
            return raw[only_key]
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

    for turn in range(max_iterations):
        resp = await client.messages.create(
            model=model,
            system=system_prompt,
            messages=messages,
            tools=all_tools,
            **request_kwargs,
        )

        usage = resp.usage
        total_input += int(getattr(usage, "input_tokens", 0))
        total_output += int(getattr(usage, "output_tokens", 0))

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

    async with client.messages.stream(
        model=model,
        max_tokens=1024,
        system=system_prompt,
        messages=_build_messages(user_input),
    ) as stream:
        async for text in stream.text_stream:
            yield text
        final = await stream.get_final_message()
        input_tokens = final.usage.input_tokens
        output_tokens = final.usage.output_tokens

    await log_llm_cost(
        session_id=session_id,
        agent_name=agent_name,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
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
