"""Onboarding reply parser.

Sonnet 4.6 low-effort per-stage parser. Replaces regex-heavy
finalise_onboarding logic with LLM-driven structured extraction. The
initial deploy used Opus 4.7 low; PROCESS.md Entry 26 documents the
swap to Sonnet 4.6 low (~$0.02/reply vs ~$0.15/reply, identical
quality on the smoke test) and the rationale under CLAUDE.md Rule 7
(structured extraction, no reasoning → Sonnet).

Each stage has its own Pydantic result schema (see `schemas.py` — `*ParseResult`).
The parser emits one of three statuses:

  - parsed: user answered the question, fields populated. State advances.
  - needs_clarification: user was vague but genuinely trying. `follow_up`
    holds a one-line targeted question. State does NOT advance.
  - off_topic: user is clearly not engaging with onboarding (trying to
    get the bot to do something unrelated, prompt-inject, or spam).
    Orchestrator shows a firm redirect and counts against a session
    abandonment budget — state does NOT advance.

User text is untrusted (CLAUDE.md Rule 10). Tier 1 Content Shield runs
before the prompt is built. Tier 2 doesn't — onboarding_parser is in
the low-stakes agent list because its tool-schema output cannot
meaningfully leak into downstream generators.

A 2000-char hard cap trims adversarial dumps before they ever reach
the API — a user cannot burn credits by pasting War & Peace.
"""

from __future__ import annotations

from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from ..config import settings
from ..llm import call_agent
from ..prompts import load_prompt
from ..schemas import (
    CareerParseResult,
    DealBreakersParseResult,
    LifeParseResult,
    MoneyParseResult,
    MotivationsParseResult,
    SamplesParseResult,
    VisaParseResult,
)
from ..validators.content_shield import shield as shield_content


T = TypeVar("T", bound=BaseModel)


_INPUT_CHAR_CAP = 2_000  # per-reply ceiling; trims adversarial dumps


# Prompt fragments live in src/trajectory/prompts/onboarding/ as plain
# Markdown so they can be diffed and versioned without touching Python.
# Each per-stage prompt is composed at module-load time as:
#     header + STAGE: <stage-description> + OUTPUT SCHEMA: <name> + common rules.
_HEADER = load_prompt("header", subdir="onboarding")
_COMMON_RULES = load_prompt("common_rules", subdir="onboarding")


def _build_prompt(stage_key: str, schema_name: str) -> str:
    stage_description = load_prompt(stage_key, subdir="onboarding")
    return (
        f"{_HEADER}\n\n"
        f"STAGE: {stage_description}\n\n"
        f"OUTPUT SCHEMA: {schema_name}\n\n"
        f"{_COMMON_RULES}"
    )


def _truncate(user_text: str) -> str:
    """Cap reply length to defend against adversarial dumps.

    A 2000-char limit is roughly 300-400 words — easily more than any
    legitimate reply to a single onboarding question. Longer replies
    are silently truncated with a marker so the parser still sees
    natural-looking text.
    """
    text = user_text.strip()
    if len(text) <= _INPUT_CHAR_CAP:
        return text
    return text[: _INPUT_CHAR_CAP - 15] + "…[TRUNCATED]"


async def _call_parser(
    *,
    system_prompt: str,
    user_text: str,
    schema: Type[T],
    agent_name: str,
) -> T:
    capped = _truncate(user_text)
    cleaned, _ = await shield_content(
        content=capped,
        source_type="user_message",
        downstream_agent="onboarding_parser",
    )
    user_input = f"USER REPLY:\n\n{cleaned.strip()}"
    # Sonnet 4.6 at effort="low" is the right rung for this job: the
    # parser does no reasoning, just structured extraction from a short
    # reply. Opus was overkill (~$0.15/reply) when Sonnet low handles
    # the same schema at ~$0.02. See PROCESS.md Entry 26 for the
    # rationale; change model here only after re-running the
    # onboarding_parser smoke test.
    return await call_agent(
        agent_name=agent_name,
        system_prompt=system_prompt,
        user_input=user_input,
        output_schema=schema,
        model=settings.sonnet_model_id,
        effort="low",
        max_retries=1,
    )


# ---------------------------------------------------------------------------
# Per-stage parsers
# ---------------------------------------------------------------------------


_CAREER_SYS = _build_prompt("career", "CareerParseResult")
_MOTIVATIONS_SYS = _build_prompt("motivations", "MotivationsParseResult")
_MONEY_SYS = _build_prompt("money", "MoneyParseResult")
_DEAL_BREAKERS_SYS = _build_prompt("deal_breakers", "DealBreakersParseResult")
_VISA_SYS = _build_prompt("visa", "VisaParseResult")
_LIFE_SYS = _build_prompt("life", "LifeParseResult")
_SAMPLES_SYS = _build_prompt("samples", "SamplesParseResult")


async def parse_career(user_text: str) -> CareerParseResult:
    return await _call_parser(
        system_prompt=_CAREER_SYS,
        user_text=user_text,
        schema=CareerParseResult,
        agent_name="onboarding_parser_career",
    )


async def parse_motivations(user_text: str) -> MotivationsParseResult:
    return await _call_parser(
        system_prompt=_MOTIVATIONS_SYS,
        user_text=user_text,
        schema=MotivationsParseResult,
        agent_name="onboarding_parser_motivations",
    )


async def parse_money(user_text: str) -> MoneyParseResult:
    return await _call_parser(
        system_prompt=_MONEY_SYS,
        user_text=user_text,
        schema=MoneyParseResult,
        agent_name="onboarding_parser_money",
    )


async def parse_deal_breakers(user_text: str) -> DealBreakersParseResult:
    return await _call_parser(
        system_prompt=_DEAL_BREAKERS_SYS,
        user_text=user_text,
        schema=DealBreakersParseResult,
        agent_name="onboarding_parser_deal_breakers",
    )


async def parse_visa(user_text: str) -> VisaParseResult:
    return await _call_parser(
        system_prompt=_VISA_SYS,
        user_text=user_text,
        schema=VisaParseResult,
        agent_name="onboarding_parser_visa",
    )


async def parse_life(user_text: str) -> LifeParseResult:
    return await _call_parser(
        system_prompt=_LIFE_SYS,
        user_text=user_text,
        schema=LifeParseResult,
        agent_name="onboarding_parser_life",
    )


async def parse_samples(user_text: str) -> SamplesParseResult:
    return await _call_parser(
        system_prompt=_SAMPLES_SYS,
        user_text=user_text,
        schema=SamplesParseResult,
        agent_name="onboarding_parser_samples",
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


_DISPATCH = {
    "career": parse_career,
    "motivations": parse_motivations,
    "money": parse_money,
    "deal_breakers": parse_deal_breakers,
    "visa": parse_visa,
    "life": parse_life,
    "samples": parse_samples,
}


async def parse_stage(stage: str, user_text: str) -> Optional[BaseModel]:
    """Dispatch to the stage-specific parser. Returns None if the stage
    has no parser (PROCESSING / DONE / START)."""
    fn = _DISPATCH.get(stage)
    if fn is None:
        return None
    return await fn(user_text)
