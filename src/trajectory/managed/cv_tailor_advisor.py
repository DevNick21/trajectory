"""CV tailor advisor (PROCESS Entry 43, Workstream D/I).

The Advisor tool surface in the SDK is more elaborate than the rest
of the managed-session shapes — Sonnet executor + Opus advisor with
mid-generation hand-offs. Until that surface is wired against this
codebase, this module delegates to the existing
`sub_agents/cv_tailor_agentic.py` which already runs a multi-turn
tool-use loop with `search_career_entries` and is functionally close
to what the Advisor tool would produce.

The intent of registering this name in `SESSIONS` is so the
`call_in_session("cv_tailor_advisor", ...)` dispatch is the canonical
draft_cv path; the underlying executor swaps to the Advisor tool in a
follow-up without any orchestrator-level change.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..schemas import CVOutput
from . import _register_session

logger = logging.getLogger(__name__)


async def run(
    *,
    jd,
    research_bundle,
    user,
    style_profile,
    star_polishes=None,
    session_id: Optional[str] = None,
) -> CVOutput:
    """Generate a CV.

    Currently delegates to `sub_agents/cv_tailor_agentic.generate` — the
    nearest functional equivalent in-tree. The Advisor-tool wiring is a
    follow-up; the dispatch name + signature stay stable.
    """
    from ..sub_agents import cv_tailor_agentic

    return await cv_tailor_agentic.generate(
        jd=jd,
        research_bundle=research_bundle,
        user=user,
        retrieved_entries=[],   # agentic path pulls on demand via tools
        style_profile=style_profile,
        star_material=star_polishes,
    )


_register_session("cv_tailor_advisor", run)
