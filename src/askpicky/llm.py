"""Single entry point for all LLM calls — provider-agnostic.

Every agent in `sub_agents/` goes through `call_agent`. The wrapper:

- Multi-provider dispatch via `llm_backends` — no vendor SDKs.
  Anthropic uses the native Messages API; every other provider
  (DeepSeek, OpenAI, any OpenAI-compatible endpoint) uses the
  unified OpenAI-compatible chat completions path.
- Forces structured output — backends handle the per-provider
  mechanism (tool_use for Anthropic, json_schema for OpenAI-compat).
- Retries on validation/citation failures (default max_retries=2).
- Logs token usage + cost via `storage.log_llm_cost`.
- Refuses non-CRITICAL calls when credits drop below warn threshold.

Anthropic-specific features (Citations API, server-side tools,
multi-turn agentic loops, Files API) are exposed as adapters that
always route through the Anthropic backend.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Awaitable, Callable, Literal, Optional, TypeVar

from pydantic import BaseModel, ValidationError

from .config import settings
from .llm_backends import get_backend
from .llm_backends.anthropic_backend import AnthropicBackend, _unwrap_parameter_value
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
_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}

Provider = Literal["anthropic", "deepseek", "openai"]


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


def _resolve_provider(agent_name: str, model: str) -> tuple[Provider, str]:
    """Determine provider and model for a given agent call.

    Priority: 1) agent_model_map override  2) model-id prefix detection
    3) default to anthropic.
    """
    agent_cfg = settings.agent_model_map.get(agent_name)
    if agent_cfg is not None:
        override_model, override_provider = agent_cfg
        return override_provider, override_model

    if "deepseek" in model.lower():
        return "deepseek", model
    if (
        "gpt-" in model.lower()
        or model.lower().startswith("o1")
        or model.lower().startswith("o3")
    ):
        return "openai", model

    return "anthropic", model


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
        "Produce a corrected output. Emit only via the tool."
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
    effort: str = "xhigh",
    max_retries: int = 2,
    session_id: Optional[str] = None,
    priority: Priority = "NORMAL",
    post_validate: Optional[Callable[[T], list[str]]] = None,
) -> T:
    """Universal agent call — works with any provider.

    Args:
        agent_name: Used for routing (managed vs plain) and cost logs.
        system_prompt: Full system prompt from AGENTS.md or prompts/*.md.
        user_input: User message or pre-built message list.
        output_schema: Pydantic model class. The backend enforces this.
        model: Override model. Defaults to opus_model_id.
        effort: Reasoning effort for models that support it.
        max_retries: Regeneration attempts after validation failure.
        session_id: For per-session cost attribution.
        priority: CRITICAL calls bypass the credit-budget refusal.
        post_validate: Optional callback (citation validator etc.).
    """
    if effort not in _EFFORT_LEVELS:
        raise ValueError(f"Unknown effort level: {effort}")

    model = model or settings.opus_model_id
    provider, model = _resolve_provider(agent_name, model)

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
            )
        except BackendError as exc:
            # Backend-level errors (auth, upstream 5xx) — don't retry on
            # auth, do retry on transient upstream failures.
            if not exc.retriable or attempt >= max_retries:
                raise AgentCallFailed(
                    f"Agent {agent_name} backend call failed: {exc}"
                ) from exc
            last_output_for_feedback = None
            last_feedback = (
                f"Backend error (attempt {attempt + 1}): {exc}. "
                "Try again with the same input."
            )
            logger.info(
                "Agent %s attempt %d: backend error — retrying.",
                agent_name,
                attempt,
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
                agent_name,
                attempt,
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
                    agent_name,
                    attempt,
                )
                continue

        logger.info(
            "agent=%s model=%s effort=%s duration_ms=%d attempts=%d "
            "input_tokens=%d output_tokens=%d "
            "cache_read_tokens=%d cache_creation_tokens=%d",
            agent_name,
            model,
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
# Re-exported for test imports (test_managed_company_investigator.py)
_unwrap_parameter_value = _unwrap_parameter_value


# ---------------------------------------------------------------------------
# Anthropic-only adapters (Citations API, server tools, multi-turn loops)
# ---------------------------------------------------------------------------


def _get_anthropic_backend() -> AnthropicBackend:
    """Return the Anthropic backend singleton."""
    backend = get_backend("anthropic")
    if not isinstance(backend, AnthropicBackend):
        raise RuntimeError(
            "Anthropic-specific features require the Anthropic backend. "
            "Set ANTHROPIC_API_KEY in your environment."
        )
    return backend


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
    """Multi-turn tool-use loop — Anthropic-only.

    The agent calls server-side tools across turns, then emits final
    structured output via the synthetic `emit_structured_output` tool.
    """
    if effort not in _EFFORT_LEVELS:
        raise ValueError(f"Unknown effort level: {effort}")

    await _enforce_credit_budget(priority)

    backend = _get_anthropic_backend()

    raw, usage = await backend.call_with_tool_loop(
        system_prompt=system_prompt,
        user_input=user_input,
        tools=tools,
        output_schema=response_schema,
        tool_executor=tool_executor,
        model=model,
        effort=effort,
        max_iterations=max_iterations,
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


from dataclasses import dataclass


@dataclass
class CitationResult:
    """Output of `call_with_citations`."""

    body: str
    text_blocks: list[dict]
    raw_citations: list[dict]
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


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
    post_validate: Optional[Callable[["CitationResult"], list[str]]] = None,
) -> CitationResult:
    """Citations-API call — Anthropic-only.

    Returns a CitationResult with body text + verbatim citations.
    """
    if effort not in _EFFORT_LEVELS:
        raise ValueError(f"Unknown effort level: {effort}")

    model = model or settings.opus_model_id
    await _enforce_credit_budget(priority)

    backend = _get_anthropic_backend()
    call_start = time.perf_counter()

    last_feedback: Optional[str] = None
    last_body: Optional[str] = None
    total_usage = LLMUsage()
    last_result: Optional[CitationResult] = None

    for attempt in range(max_retries + 1):
        prompt = user_input
        if last_feedback is not None:
            prompt = (
                f"{user_input}\n\n"
                f"Your previous attempt was rejected. Here is what you "
                f"produced:\n\n```\n{last_body}\n```\n\n"
                f"Rejection reason(s):\n{last_feedback}\n\n"
                "Produce a corrected output now."
            )

        text_blocks, raw_citations, usage, body_text = (
            await backend.call_with_citations(
                system_prompt=system_prompt,
                user_input=prompt,
                documents=documents,
                model=model,
                effort=effort,
                extra_tools=extra_tools,
                cache_documents=cache_documents,
            )
        )

        total_usage.input_tokens += usage.input_tokens
        total_usage.output_tokens += usage.output_tokens
        total_usage.cache_read_tokens += usage.cache_read_tokens
        total_usage.cache_creation_tokens += usage.cache_creation_tokens

        result = CitationResult(
            body=body_text,
            text_blocks=text_blocks,
            raw_citations=raw_citations,
            input_tokens=total_usage.input_tokens,
            output_tokens=total_usage.output_tokens,
            cache_read_tokens=total_usage.cache_read_tokens,
            cache_creation_tokens=total_usage.cache_creation_tokens,
        )
        last_result = result

        if post_validate is not None:
            failures = post_validate(result)
            if failures:
                last_body = result.body
                last_feedback = "- " + "\n- ".join(failures)
                logger.info(
                    "Agent %s attempt %d (citations): post-validation "
                    "failed — retrying.",
                    agent_name,
                    attempt,
                )
                continue

        await log_llm_cost(
            session_id=session_id,
            agent_name=agent_name,
            model=model,
            input_tokens=total_usage.input_tokens,
            output_tokens=total_usage.output_tokens,
            cache_read_tokens=total_usage.cache_read_tokens,
            cache_creation_tokens=total_usage.cache_creation_tokens,
        )

        logger.info(
            "agent=%s adapter=citations model=%s effort=%s "
            "duration_ms=%d attempts=%d blocks=%d citations=%d "
            "input_tokens=%d output_tokens=%d "
            "cache_read=%d cache_creation=%d",
            agent_name,
            model,
            effort,
            int((time.perf_counter() - call_start) * 1000),
            attempt + 1,
            len(text_blocks),
            len(raw_citations),
            total_usage.input_tokens,
            total_usage.output_tokens,
            total_usage.cache_read_tokens,
            total_usage.cache_creation_tokens,
        )
        return result

    await log_llm_cost(
        session_id=session_id,
        agent_name=agent_name,
        model=model,
        input_tokens=total_usage.input_tokens,
        output_tokens=total_usage.output_tokens,
        cache_read_tokens=total_usage.cache_read_tokens,
        cache_creation_tokens=total_usage.cache_creation_tokens,
    )
    raise AgentCallFailed(
        f"Agent {agent_name} (citations) failed after "
        f"{max_retries + 1} attempts. "
        f"Last feedback:\n{last_feedback}"
    )


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
    """Schema-dense call WITH server-side tools — Anthropic-only.

    `server_tools` accepts Anthropic server-side tool dicts:
      - {"type": "web_search_20260209", ...}
      - {"type": "code_execution_20260209", ...}

    The model must call `emit_structured_output` once with the final answer.
    """
    if effort not in _EFFORT_LEVELS:
        raise ValueError(f"Unknown effort level: {effort}")

    model = model or settings.opus_model_id
    await _enforce_credit_budget(priority)

    backend = _get_anthropic_backend()

    from .llm_backends.anthropic_backend import _schema_to_tool

    output_tool = _schema_to_tool(output_schema)
    all_tools = [output_tool, *server_tools]

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

        raw_output: Optional[dict] = None
        agg_usage = LLMUsage()

        # Inner loop: handle server-side tool interleaving (max 8 turns)
        for _ in range(8):
            is_last_inner = False

            # Manually handle this loop's messages accumulation
            body = {
                "model": model,
                "messages": messages,
                "tools": all_tools,
                "max_tokens": 4_096,
                "tool_choice": {"type": "auto"},
            }

            if isinstance(system_prompt, str):
                body["system"] = system_prompt
            else:
                body["system"] = system_prompt

            if "opus-4-7" in model.lower():
                body["thinking"] = {"type": "adaptive"}
                body["max_tokens"] = 12_000 if effort in {"xhigh", "max"} else 8_000

            if effort in {"low", "medium", "high", "xhigh", "max"} and "haiku" not in model.lower():
                body["output_config"] = {"effort": effort}

            resp_data = await backend._post("/v1/messages", body)
            turn_usage = LLMUsage(
                input_tokens=int(
                    (resp_data.get("usage") or {}).get("input_tokens", 0)
                ),
                output_tokens=int(
                    (resp_data.get("usage") or {}).get("output_tokens", 0)
                ),
            )
            agg_usage.input_tokens += turn_usage.input_tokens
            agg_usage.output_tokens += turn_usage.output_tokens

            emit = next(
                (
                    b for b in resp_data.get("content", [])
                    if b.get("type") == "tool_use"
                    and b.get("name") == "emit_structured_output"
                ),
                None,
            )
            if emit is not None:
                raw_output = _unwrap_parameter_value(emit.get("input", {}))
                break

            from .llm_backends.anthropic_backend import _preserve_assistant_blocks

            messages.append(
                {
                    "role": "assistant",
                    "content": _preserve_assistant_blocks(
                        resp_data.get("content", [])
                    ),
                }
            )

            if resp_data.get("stop_reason") in {"end_turn", "stop_sequence"}:
                break

        await log_llm_cost(
            session_id=session_id,
            agent_name=agent_name,
            model=model,
            input_tokens=agg_usage.input_tokens,
            output_tokens=agg_usage.output_tokens,
            cache_read_tokens=0,
            cache_creation_tokens=0,
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
                f"Output failed Pydantic validation for "
                f"{output_schema.__name__}.\n{ve}"
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
            "agent=%s adapter=tools model=%s effort=%s "
            "duration_ms=%d attempts=%d "
            "input_tokens=%d output_tokens=%d "
            "server_tools=%s",
            agent_name,
            model,
            effort,
            int((time.perf_counter() - call_start) * 1000),
            attempt + 1,
            agg_usage.input_tokens,
            agg_usage.output_tokens,
            [t.get("name") for t in server_tools],
        )
        return parsed

    raise AgentCallFailed(
        f"Agent {agent_name} (with-tools) failed after "
        f"{max_retries + 1} attempts. "
        f"Last feedback: {last_feedback}"
    )


# ---------------------------------------------------------------------------
# Files API — Anthropic-only PDF upload
# ---------------------------------------------------------------------------


async def upload_pdf(pdf_bytes: bytes, filename: str = "offer.pdf") -> str:
    """Upload a PDF to Anthropic's Beta Files API. Returns file_id."""
    backend = _get_anthropic_backend()
    return await backend.upload_pdf(pdf_bytes, filename)


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
# Managed agent placeholder (future)
# ---------------------------------------------------------------------------


async def call_in_session(**_kwargs: Any) -> Any:
    """Placeholder for managed-agent in-session calls (not yet implemented)."""
    raise NotImplementedError(
        "call_in_session is not yet implemented. "
        "Managed agents are on the roadmap but not wired in this release."
    )
