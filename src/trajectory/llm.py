"""Single entry point for all LLM calls.

Every agent in `sub_agents/` goes through `call_agent`. The wrapper:

- Routes Phase 1 / Phase 4 fan-out sessions through Managed Agents (beta
  header `managed-agents-2026-04-01`) when `settings.use_managed_agents`,
  otherwise through the plain Messages API.
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
from typing import Any, AsyncIterator, Callable, Literal, Optional, TypeVar

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
# Routing
# ---------------------------------------------------------------------------


def _routes_through_managed_agents(agent_name: str) -> bool:
    if not settings.use_managed_agents:
        return False
    return agent_name.startswith(("phase_1_", "phase_4_fanout_"))


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

    if _routes_through_managed_agents(agent_name):
        call_fn = _call_via_managed_agents
    else:
        call_fn = _call_via_messages_api

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

        try:
            raw_output, input_tokens, output_tokens = await call_fn(
                agent_name=agent_name,
                system_prompt=system_prompt,
                messages=messages,
                output_schema=output_schema,
                model=model,
                effort=effort,
            )
        except Exception as e:
            # Managed Agents failures fall back to plain Messages API once.
            if call_fn is _call_via_managed_agents:
                logger.warning(
                    "Managed Agents failed for %s (%s). Falling back to Messages API.",
                    agent_name,
                    e,
                )
                call_fn = _call_via_messages_api
                continue
            raise

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

    max_tokens = 4096
    extra_kwargs: dict[str, Any] = {}
    thinking_enabled = effort == "xhigh"
    if thinking_enabled:
        # Extended thinking requires `budget_tokens < max_tokens` and
        # forbids `tool_choice` in {"tool", "any"} — we therefore allow the
        # model to choose the single-tool and bump max_tokens to leave room
        # for the final answer on top of the thinking budget.
        budget_tokens = 8000
        extra_kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget_tokens}
        max_tokens = budget_tokens + 4096

    tool_choice: dict[str, Any]
    if thinking_enabled:
        tool_choice = {"type": "auto"}
    else:
        tool_choice = {"type": "tool", "name": tool["name"]}

    resp = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,
        tools=[tool],
        tool_choice=tool_choice,
        **extra_kwargs,
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

    raw = tool_use_block.input
    if not isinstance(raw, dict):
        raise AgentCallFailed(
            f"Agent {agent_name} tool_use.input was not a JSON object."
        )

    usage = resp.usage
    return raw, int(usage.input_tokens), int(usage.output_tokens)


# ---------------------------------------------------------------------------
# Backend: Managed Agents beta
# ---------------------------------------------------------------------------


async def _call_via_managed_agents(
    *,
    agent_name: str,
    system_prompt: str,
    messages: list[dict],
    output_schema: type[BaseModel],
    model: str,
    effort: str,
) -> tuple[dict, int, int]:
    """Managed Agents backend.

    Skeleton note: the exact beta SDK surface may shift — we route through
    the Anthropic client with the beta header applied. If this fails, the
    caller in `call_agent` falls back to the plain Messages API.
    """
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        default_headers={"anthropic-beta": settings.managed_agents_beta_header},
    )
    tool = _schema_to_tool(output_schema)

    max_tokens = 4096
    extra_kwargs: dict[str, Any] = {}
    thinking_enabled = effort == "xhigh"
    if thinking_enabled:
        # Same constraints as the plain Messages backend: budget_tokens must
        # be strictly less than max_tokens, and tool_choice cannot pin a
        # single tool when extended thinking is enabled.
        budget_tokens = 8000
        extra_kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget_tokens}
        max_tokens = budget_tokens + 4096

    tool_choice: dict[str, Any]
    if thinking_enabled:
        tool_choice = {"type": "auto"}
    else:
        tool_choice = {"type": "tool", "name": tool["name"]}

    resp = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,
        tools=[tool],
        tool_choice=tool_choice,
        metadata={"agent_name": agent_name},
        **extra_kwargs,
    )

    tool_use_block = next(
        (b for b in resp.content if getattr(b, "type", None) == "tool_use"),
        None,
    )
    if tool_use_block is None:
        raise AgentCallFailed(
            f"Managed-Agents call for {agent_name} did not emit tool_use."
        )
    raw = tool_use_block.input
    if not isinstance(raw, dict):
        raise AgentCallFailed(
            f"Managed-Agents call for {agent_name} returned non-dict."
        )

    usage = resp.usage
    return raw, int(usage.input_tokens), int(usage.output_tokens)


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
