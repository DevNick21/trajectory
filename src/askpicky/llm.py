"""Single entry point for all LLM calls — provider-agnostic.

Every agent in `sub_agents/` goes through `call_agent`. The wrapper:

- Multi-provider dispatch via `llm_backends` — no vendor SDKs.
  Every provider uses the unified OpenAI-compatible chat completions path.
- Forces structured output via json_schema or json_object.
- Three-tier model routing: fast / normal / strong.
- Retries on validation/citation failures (default max_retries=2).
- Logs token usage + cost via `storage.log_llm_cost`.
- Refuses non-CRITICAL calls when credits drop below warn threshold.
- Multi-turn tool use is provider-agnostic (OpenAI-compat tool calling).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Awaitable, Callable, Literal, Optional, TypeVar

from pydantic import BaseModel, ValidationError

from .config import settings
from .llm_backends import get_backend
from .llm_backends.base import BackendError, LLMUsage
from .storage import log_llm_cost, total_cost_usd

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class CreditBudgetExceeded(RuntimeError):
    """Raised when a non-CRITICAL call is refused due to low remaining credits."""


class AgentCallFailed(RuntimeError):
    """Raised when an agent fails to produce valid output after retries."""


Priority = Literal["CRITICAL", "NORMAL"]
Tier = Literal["fast", "normal", "strong"]
_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}

Provider = Literal["deepseek", "openai"]

# Tier → (model_id, provider) lookup table.
_TIER_LOOKUP: dict[str, tuple[str, str]] = {
    "fast": settings.TIER_FAST,
    "normal": settings.TIER_NORMAL,
    "strong": settings.TIER_STRONG,
}


# ---------------------------------------------------------------------------
# Tier resolution
# ---------------------------------------------------------------------------


def _resolve_tier(agent_name: str) -> tuple[str, str]:
    """Return (model_id, provider) for the given agent based on its tier."""
    tier = settings.agent_tier_map.get(agent_name, "normal")
    return _TIER_LOOKUP[tier]


# ---------------------------------------------------------------------------
# Prompt construction helpers
# ---------------------------------------------------------------------------


def _build_messages(user_input: str | list[dict]) -> list[dict]:
    if isinstance(user_input, str):
        return [{"role": "user", "content": user_input}]
    return list(user_input)


def _format_retry_feedback(previous_output: Any, feedback: str) -> str:
    return (
        "Your previous attempt was rejected. Here is what you produced:\n\n"
        f"```\n{json.dumps(previous_output, default=str, indent=2)}\n```\n\n"
        "Rejection reason(s):\n"
        f"{feedback}\n\n"
        "Produce a corrected output."
    )


# ---------------------------------------------------------------------------
# Core call — provider-agnostic structured output
# ---------------------------------------------------------------------------


async def call_agent(
    agent_name: str,
    system_prompt: str,
    user_input: str | list[dict],
    output_schema: type[T],
    model: Optional[str] = None,
    provider: Optional[Provider] = None,
    effort: str = "xhigh",
    max_retries: int = 2,
    session_id: Optional[str] = None,
    priority: Priority = "NORMAL",
    post_validate: Optional[Callable[[T], list[str]]] = None,
    max_tokens: int = 4_096,
) -> T:
    """Universal agent call — works with any provider.

    Args:
        agent_name: Used for tier routing and cost logs.
        system_prompt: Full system prompt from prompts/*.md.
        user_input: User message or pre-built message list.
        output_schema: Pydantic model class. The backend enforces this.
        model: Override model. Defaults to the agent's tier model.
        provider: Override provider. Defaults to the agent's tier provider.
        effort: Reasoning effort for models that support it.
        max_retries: Regeneration attempts after validation failure.
        session_id: For per-session cost attribution.
        priority: CRITICAL calls bypass the credit-budget refusal.
        post_validate: Optional callback (citation validator etc.).
    """
    if effort not in _EFFORT_LEVELS:
        raise ValueError(f"Unknown effort level: {effort}")

    if model is None or provider is None:
        tier_model, tier_provider = _resolve_tier(agent_name)
        model = model or tier_model
        provider = provider or tier_provider

    await _enforce_credit_budget(priority)

    backend = get_backend(provider)

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

        try:
            result = await backend.call(
                system_prompt=system_prompt,
                messages=messages,
                output_schema=output_schema,
                model=model,
                effort=effort,
                max_tokens=max_tokens,
                provider=provider,
            )
        except BackendError as exc:
            if not exc.retriable or attempt >= max_retries:
                raise AgentCallFailed(
                    f"Agent {agent_name} backend call failed: {exc}"
                ) from exc
            last_output_for_feedback = None
            if "truncated" in str(exc).lower():
                new_max = max_tokens * 2
                logger.info(
                    "Agent %s: response truncated at %d tokens, "
                    "retrying with max_tokens=%d",
                    agent_name, max_tokens, new_max,
                )
                max_tokens = new_max
            last_feedback = (
                f"Backend error (attempt {attempt + 1}): {exc}. "
                "Try again with the same input."
            )
            logger.info(
                "Agent %s attempt %d: backend error — retrying.",
                agent_name, attempt,
            )
            continue

        raw_output = result.raw
        usage = result.usage

        await log_llm_cost(
            session_id=session_id,
            agent_name=agent_name,
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_creation_tokens=usage.cache_creation_tokens,
        )

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
                agent_name, attempt,
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
                logger.info(
                    "Agent %s attempt %d: post-validation failed — retrying.",
                    agent_name, attempt,
                )
                continue

        logger.info(
            "agent=%s model=%s provider=%s effort=%s duration_ms=%d attempts=%d "
            "input_tokens=%d output_tokens=%d "
            "cache_read_tokens=%d cache_creation_tokens=%d",
            agent_name,
            model,
            provider,
            effort,
            int((time.perf_counter() - call_start) * 1000),
            attempt + 1,
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_tokens,
            usage.cache_creation_tokens,
        )
        return parsed

    raise AgentCallFailed(
        f"Agent {agent_name} failed after {max_retries + 1} attempts. "
        f"Last feedback: {last_feedback}"
    )


# Backwards-compat aliases
call_structured = call_agent


# ---------------------------------------------------------------------------
# Multi-turn tool use — provider-agnostic (OpenAI-compat tool calling)
# ---------------------------------------------------------------------------

_EMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_structured_output",
        "description": "Emit the final structured output. Call EXACTLY once at the end.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": True},
    },
}


async def call_agent_with_tools(
    *,
    agent_name: str,
    system_prompt: str,
    user_input: str,
    tools: list[dict],
    tool_executor: Callable[[str, dict], Awaitable[str]],
    response_schema: type[T],
    model: Optional[str] = None,
    provider: Optional[str] = None,
    effort: str = "xhigh",
    session_id: Optional[str] = None,
    max_iterations: int = 10,
    priority: Priority = "NORMAL",
    max_tokens: int = 4_096,
) -> T:
    """Multi-turn tool-use loop — provider-agnostic.

    Uses OpenAI-compat tool calling (supported by DeepSeek and OpenAI).
    """
    if effort not in _EFFORT_LEVELS:
        raise ValueError(f"Unknown effort level: {effort}")

    if model is None or provider is None:
        tier_model, tier_provider = _resolve_tier(agent_name)
        model = model or tier_model
        provider = provider or tier_provider

    await _enforce_credit_budget(priority)

    backend = get_backend(provider)

    # Convert tools from Anthropic-style to OpenAI function format
    openai_tools = _to_openai_tools(tools) + [_EMIT_TOOL]

    raw, usage = await _tool_loop(
        backend=backend,
        model=model,
        system_prompt=system_prompt,
        user_input=user_input,
        tools=openai_tools,
        tool_executor=tool_executor,
        effort=effort,
        max_iterations=max_iterations,
        max_tokens=max_tokens,
    )

    await log_llm_cost(
        session_id=session_id,
        agent_name=agent_name,
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_creation_tokens=usage.cache_creation_tokens,
    )

    return response_schema.model_validate(raw)


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    """Convert Anthropic-style tool defs to OpenAI function format."""
    result = []
    for t in tools:
        params = t.get("input_schema", {})
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": params,
            },
        })
    return result


async def _tool_loop(
    *,
    backend,
    model: str,
    system_prompt: str,
    user_input: str,
    tools: list[dict],
    tool_executor,
    effort: str,
    max_iterations: int,
    max_tokens: int,
) -> tuple[dict, LLMUsage]:
    """Execute the multi-turn tool-use loop using OpenAI-compat API."""
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]
    total_usage = LLMUsage()

    for turn in range(max_iterations):
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if tools:
            body["tools"] = tools

        resp_data = await backend._post("/v1/chat/completions", body)
        total_usage = _accumulate_usage(total_usage, resp_data)

        choice = (resp_data.get("choices") or [{}])[0]
        msg = choice.get("message", {})

        tool_calls = msg.get("tool_calls") or []

        # Record assistant response in history
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": msg.get("content") or ""}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        # Check for emit_structured_output
        emit_call = next(
            (tc for tc in tool_calls
             if tc.get("function", {}).get("name") == "emit_structured_output"),
            None,
        )
        if emit_call is not None:
            try:
                raw = json.loads(emit_call["function"].get("arguments", "{}"))
            except json.JSONDecodeError:
                raise BackendError("emit_structured_output arguments was not valid JSON")
            if not isinstance(raw, dict):
                raise BackendError("emit_structured_output arguments was not a JSON object")
            return raw, total_usage

        if not tool_calls:
            messages.append({
                "role": "user",
                "content": "You must call a tool. Use emit_structured_output when done.",
            })
            continue

        # Execute each tool call and append results
        for tc in tool_calls:
            func = tc.get("function", {})
            tool_name = func.get("name", "")
            if tool_name == "emit_structured_output":
                continue
            try:
                tool_input = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                tool_input = {}
            tool_result = await tool_executor(tool_name, tool_input)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", f"call_{turn}"),
                "content": tool_result,
            })

    raise AgentCallFailed(
        f"Tool-use loop reached max iterations ({max_iterations}) without "
        f"calling emit_structured_output."
    )


def _accumulate_usage(total: LLMUsage, resp_data: dict) -> LLMUsage:
    usage = resp_data.get("usage", {})
    total.input_tokens += usage.get("prompt_tokens", 0)
    total.output_tokens += usage.get("completion_tokens", 0)
    return total


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


# ---------------------------------------------------------------------------
# Managed agent placeholder (not yet implemented)
# ---------------------------------------------------------------------------


async def call_in_session(**_kwargs: Any) -> Any:
    """Placeholder for managed-agent in-session calls (not yet implemented)."""
    raise NotImplementedError(
        "call_in_session is not yet implemented. "
        "Managed agents are on the roadmap but not wired in this release."
    )
