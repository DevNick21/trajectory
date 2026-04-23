"""Prompt Auditor — build-time-only agent.

AGENTS.md §17. Critiques another agent's system prompt against
Trajectory's discipline checklist. Not part of the runtime pipeline;
developers invoke it via `scripts/audit_prompt.py`.

Never sees production user data. Never runs at runtime.
"""

from __future__ import annotations

from ..prompts import load_prompt

from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import PromptAuditReport


SYSTEM_PROMPT = load_prompt("prompt_auditor")


async def audit(
    audited_agent_name: str,
    audited_system_prompt: str,
    audited_output_schema: str,
    input_sources: list[str],
    session_id: Optional[str] = None,
) -> PromptAuditReport:
    """Run the Prompt Auditor against another agent's system prompt.

    Args:
        audited_agent_name: Name of the agent being audited.
        audited_system_prompt: Full verbatim text of that agent's SYSTEM_PROMPT.
        audited_output_schema: Pydantic model name + its fields, as prose.
        input_sources: List of `"<input_name>: TRUSTED|UNTRUSTED"` labels.
        session_id: Optional — threaded through for cost logging.
    """
    user_input = (
        f"AUDITED AGENT: {audited_agent_name}\n\n"
        f"OUTPUT SCHEMA: {audited_output_schema}\n\n"
        f"INPUT SOURCES (trusted/untrusted labelled):\n"
        + "\n".join(f"  - {s}" for s in input_sources)
        + "\n\n"
        "AUDITED SYSTEM PROMPT (verbatim, between fences):\n"
        "```\n"
        f"{audited_system_prompt}\n"
        "```\n"
    )

    return await call_agent(
        agent_name="prompt_auditor",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=PromptAuditReport,
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
        priority="NORMAL",
    )
