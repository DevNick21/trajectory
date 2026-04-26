"""Multi-provider structured-output dispatcher (PROCESS Entry 44).

ONE call site uses this: `cv_tailor` when
`enable_multi_provider_cv_tailor=True`. ATS host -> provider via
`ats_routing.provider_for_url`; this module turns "provider name +
schema + prompt" into "validated Pydantic instance" regardless of
which vendor's SDK is doing the work.

Shape parity:
- Each adapter exposes `async call_structured(...)` with the same
  signature as `llm.call_structured`.
- Each adapter logs cost via `storage.log_llm_cost` with an
  `agent_name` suffix that includes the provider for attribution.
- Each adapter retries on schema-validation failure (max 2 attempts).

Provider notes:
- **anthropic**: delegates to `llm.call_structured` (no behavioural change).
- **openai**: `client.chat.completions.parse(response_format=Schema)` —
  guaranteed structured outputs on gpt-4o / gpt-5.
- **cohere**: `client.chat(response_format={"type": "json_object", ...})`.
  Cohere's structured-output is less strict than OpenAI's; we add a
  Pydantic re-validation pass + one retry on failure.

Citation discipline note: cv_tailor produces `CVOutput` with embedded
`Citation` objects. The Anthropic-only first-party Citations API is
NOT in this path — cv_tailor uses `call_structured` (tool_use envelope)
on Anthropic too. So citation enforcement is `validators/citations.py`
in all four providers — no regression vs the current Anthropic path.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional, TypeVar

from pydantic import BaseModel, ValidationError

from .ats_routing import Provider
from .config import settings
from .storage import log_llm_cost

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class ProviderUnavailable(RuntimeError):
    """Raised when the requested provider's API key isn't configured
    or the SDK isn't installed."""


# ===========================================================================
# Public dispatcher
# ===========================================================================


async def call_structured(
    *,
    provider: Provider,
    agent_name: str,
    system_prompt: str,
    user_input: str,
    output_schema: type[T],
    model: Optional[str] = None,
    effort: str = "xhigh",
    max_retries: int = 2,
    session_id: Optional[str] = None,
) -> T:
    """Provider-agnostic structured-output call. Dispatches by `provider`.

    `model` defaults to the per-provider model in settings.
    `effort` is honoured on Anthropic (xhigh/high/medium/low) and best-
    effort mapped on the others (high effort -> larger model where
    available, else ignored).
    """
    if provider == "anthropic":
        return await _anthropic_call(
            agent_name=agent_name,
            system_prompt=system_prompt,
            user_input=user_input,
            output_schema=output_schema,
            model=model,
            effort=effort,
            max_retries=max_retries,
            session_id=session_id,
        )
    if provider == "openai":
        return await _openai_call(
            agent_name=agent_name,
            system_prompt=system_prompt,
            user_input=user_input,
            output_schema=output_schema,
            model=model,
            max_retries=max_retries,
            session_id=session_id,
        )
    if provider == "cohere":
        return await _cohere_call(
            agent_name=agent_name,
            system_prompt=system_prompt,
            user_input=user_input,
            output_schema=output_schema,
            model=model,
            max_retries=max_retries,
            session_id=session_id,
        )
    raise ProviderUnavailable(f"Unknown provider: {provider!r}")


# ===========================================================================
# Anthropic adapter — delegate to existing llm.call_structured
# ===========================================================================


async def _anthropic_call(
    *,
    agent_name: str,
    system_prompt: str,
    user_input: str,
    output_schema: type[T],
    model: Optional[str],
    effort: str,
    max_retries: int,
    session_id: Optional[str],
) -> T:
    from .llm import call_structured as anthropic_call_structured
    return await anthropic_call_structured(
        agent_name=f"{agent_name}__anthropic",
        system_prompt=system_prompt,
        user_input=user_input,
        output_schema=output_schema,
        model=model or settings.opus_model_id,
        effort=effort,
        max_retries=max_retries,
        session_id=session_id,
    )


# ===========================================================================
# OpenAI adapter — chat.completions.parse with response_format=Schema
# ===========================================================================


_openai_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        if not settings.openai_api_key:
            raise ProviderUnavailable(
                "OPENAI_API_KEY is not set in .env or environment."
            )
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ProviderUnavailable(
                "openai SDK not installed (pip install openai)"
            ) from exc
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


async def _openai_call(
    *,
    agent_name: str,
    system_prompt: str,
    user_input: str,
    output_schema: type[T],
    model: Optional[str],
    max_retries: int,
    session_id: Optional[str],
) -> T:
    client = _get_openai_client()
    model = model or settings.openai_model_id

    last_feedback: Optional[str] = None
    call_start = time.perf_counter()

    for attempt in range(max_retries + 1):
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]
        if last_feedback is not None:
            messages.append({
                "role": "user",
                "content": (
                    "Your previous attempt failed Pydantic validation:\n"
                    f"{last_feedback}\n\n"
                    "Produce a corrected output. Match the schema exactly."
                ),
            })

        try:
            resp = await client.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=output_schema,
                max_completion_tokens=8_000,
            )
        except Exception as exc:
            # Some accounts don't have parse(); fall back to JSON mode.
            logger.warning(
                "openai.parse failed (%s); falling back to JSON mode.", exc,
            )
            return await _openai_json_mode_call(
                client=client,
                agent_name=agent_name,
                model=model,
                messages=messages,
                output_schema=output_schema,
                session_id=session_id,
                call_start=call_start,
            )

        usage = resp.usage
        await log_llm_cost(
            session_id=session_id,
            agent_name=f"{agent_name}__openai",
            model=model,
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        )

        message = resp.choices[0].message
        if getattr(message, "refusal", None):
            raise RuntimeError(
                f"OpenAI refused: {message.refusal}"
            )

        parsed = getattr(message, "parsed", None)
        if parsed is not None:
            logger.info(
                "agent=%s adapter=openai model=%s duration_ms=%d "
                "attempts=%d input_tokens=%d output_tokens=%d",
                agent_name, model,
                int((time.perf_counter() - call_start) * 1000),
                attempt + 1,
                getattr(usage, "prompt_tokens", 0),
                getattr(usage, "completion_tokens", 0),
            )
            return parsed

        # Manual fallback: parse content as JSON, validate.
        try:
            raw = json.loads(message.content or "{}")
            return output_schema.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as ve:
            last_feedback = str(ve)
            continue

    raise RuntimeError(
        f"OpenAI agent {agent_name} failed after {max_retries + 1} attempts. "
        f"Last feedback: {last_feedback}"
    )


async def _openai_json_mode_call(
    *,
    client,
    agent_name: str,
    model: str,
    messages: list[dict],
    output_schema: type[T],
    session_id: Optional[str],
    call_start: float,
) -> T:
    """Fallback path when chat.completions.parse isn't available — uses
    JSON mode + Pydantic post-validation."""
    schema_hint = json.dumps(output_schema.model_json_schema(), indent=2)
    messages = list(messages)
    messages[0] = {
        "role": "system",
        "content": (
            messages[0]["content"]
            + "\n\nReturn ONE JSON object matching this schema exactly:\n```json\n"
            + schema_hint
            + "\n```\nNo prose, no Markdown fences in the response itself."
        ),
    }
    resp = await client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        max_completion_tokens=8_000,
    )
    usage = resp.usage
    await log_llm_cost(
        session_id=session_id,
        agent_name=f"{agent_name}__openai",
        model=model,
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
    )
    raw = json.loads(resp.choices[0].message.content or "{}")
    parsed = output_schema.model_validate(raw)
    logger.info(
        "agent=%s adapter=openai_json model=%s duration_ms=%d "
        "input_tokens=%d output_tokens=%d",
        agent_name, model,
        int((time.perf_counter() - call_start) * 1000),
        getattr(usage, "prompt_tokens", 0),
        getattr(usage, "completion_tokens", 0),
    )
    return parsed


# ===========================================================================
# Cohere adapter — chat with response_format=json_object + retry
# ===========================================================================


_cohere_client = None


def _get_cohere_client():
    global _cohere_client
    if _cohere_client is None:
        if not settings.cohere_api_key:
            raise ProviderUnavailable(
                "COHERE_API_KEY is not set in .env or environment."
            )
        try:
            import cohere
        except ImportError as exc:
            raise ProviderUnavailable(
                "cohere SDK not installed (pip install cohere)"
            ) from exc
        _cohere_client = cohere.AsyncClientV2(api_key=settings.cohere_api_key)
    return _cohere_client


async def _cohere_call(
    *,
    agent_name: str,
    system_prompt: str,
    user_input: str,
    output_schema: type[T],
    model: Optional[str],
    max_retries: int,
    session_id: Optional[str],
) -> T:
    client = _get_cohere_client()
    model = model or settings.cohere_model_id

    schema_hint = json.dumps(output_schema.model_json_schema(), indent=2)
    last_feedback: Optional[str] = None
    call_start = time.perf_counter()

    for attempt in range(max_retries + 1):
        sys = (
            system_prompt
            + "\n\nReturn ONE JSON object matching this schema exactly:\n"
            + "```json\n" + schema_hint + "\n```"
        )
        if last_feedback is not None:
            sys += (
                "\n\nYour previous attempt failed validation:\n"
                + last_feedback
                + "\nProduce a corrected output."
            )

        messages = [
            {"role": "system", "content": sys},
            {"role": "user", "content": user_input},
        ]

        # Pydantic schemas with bare `dict` fields (e.g. CVOutput.contact)
        # produce JSON Schema with `type: object` and no `properties`,
        # which Cohere's `response_format.schema` rejects ("`object` type
        # must specify `properties`"). The `schema` param is also flagged
        # experimental by the SDK. Use plain `json_object` mode and rely
        # on Pydantic re-validation — `schema_hint` is already in the
        # system prompt above so the model sees the structure.
        resp = await client.chat(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=4_000,
        )

        # Cohere v2 returns text inside resp.message.content[0].text
        try:
            text = resp.message.content[0].text
        except (AttributeError, IndexError, TypeError) as exc:
            last_feedback = f"Could not extract text from Cohere response: {exc}"
            continue

        # Token counts
        usage = getattr(resp, "usage", None)
        billed = getattr(usage, "billed_units", None) if usage else None
        input_tokens = int(getattr(billed, "input_tokens", 0) or 0) if billed else 0
        output_tokens = int(getattr(billed, "output_tokens", 0) or 0) if billed else 0
        await log_llm_cost(
            session_id=session_id,
            agent_name=f"{agent_name}__cohere",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        try:
            raw = json.loads(text)
            parsed = output_schema.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as ve:
            last_feedback = str(ve)
            continue

        logger.info(
            "agent=%s adapter=cohere model=%s duration_ms=%d attempts=%d "
            "input_tokens=%d output_tokens=%d",
            agent_name, model,
            int((time.perf_counter() - call_start) * 1000),
            attempt + 1, input_tokens, output_tokens,
        )
        return parsed

    raise RuntimeError(
        f"Cohere agent {agent_name} failed after {max_retries + 1} attempts. "
        f"Last feedback: {last_feedback}"
    )


# Llama adapter removed 2026-04-26 (PROCESS Entry 44 follow-up). The
# only ATS routed to Llama was Crelate (1/25), reassigned to Anthropic.
# `git log -- src/trajectory/llm_providers.py` recovers the adapter if
# it ever needs to come back.
