"""Verdict deep-research (PROCESS Entry 43, Workstream D/I).

"Money-no-object" verdict variant: the agent gets Web Search + Web
Fetch server tools and uses them to enrich the verdict with live
information (recent news, Reddit threads about the company, leaver
signals) BEFORE issuing a verdict.

Triggered when `settings.enable_verdict_ensemble=True`. The
orchestrator runs this in parallel with the standard verdict and
conservative-merges (NO_GO wins, union of blockers).

Implementation: NOT a full Managed Agents session — just a
`call_with_tools` call attaching Web Search + Web Fetch. The agent
operates in the standard Messages API but with live web access.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..config import settings
from ..llm import call_with_tools
from ..prompts import load_prompt
from ..schemas import ResearchBundle, UserProfile, Verdict
from ..server_tools import WEB_FETCH, WEB_SEARCH
from . import _register_session

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT_BASE = load_prompt("verdict")
_DEEP_ADDENDUM = """

## Deep-research mode (enable_verdict_ensemble=True)

You have Web Search and Web Fetch tools available. Before issuing the
verdict, do up to 5 targeted lookups:
  - Recent news mentions of the company (layoffs, funding, leadership
    change, scandals)
  - Reddit threads on r/cscareerquestionsEU + r/UKJobs about the
    company in the last 12 months
  - LinkedIn-public-snippets: recent leaver signals (be careful — only
    aggregate patterns, never quote individuals)
  - Companies House / official filings for the most recent year

Surface anything material as a stretch_concern with a citation.
Never let the live-web augmentation flip a NO_GO to a GO; it can only
add stretch_concerns or hard_blockers.
"""

SYSTEM_PROMPT = _SYSTEM_PROMPT_BASE + _DEEP_ADDENDUM


async def run(
    *,
    user: UserProfile,
    research_bundle: ResearchBundle,
    session_id: Optional[str] = None,
) -> Verdict:
    """Issue a verdict augmented by live-web research."""
    user_input = json.dumps({
        "user_profile": user.model_dump(mode="json"),
        "research_bundle": research_bundle.model_dump(mode="json"),
        "instruction": (
            "Issue a Verdict per your system prompt. Use the Web Search "
            "+ Web Fetch tools to enrich with live information before "
            "deciding. Cite every reasoning_point."
        ),
    }, default=str)

    verdict = await call_with_tools(
        agent_name="verdict_deep_research",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=Verdict,
        server_tools=[WEB_SEARCH, WEB_FETCH],
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
    )
    logger.info(
        "verdict_deep_research: decision=%s blockers=%d stretch=%d",
        verdict.decision, len(verdict.hard_blockers),
        len(verdict.stretch_concerns),
    )
    return verdict


_register_session("verdict_deep_research", run)
