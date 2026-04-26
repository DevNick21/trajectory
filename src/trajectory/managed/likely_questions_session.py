"""Managed likely-questions generator (PROCESS Entry 45).

Live interview-experience-equipped question prediction. Where the
in-process `sub_agents/likely_questions.py` predicts from JD + culture
claims alone, this variant does up to 4 web searches to pull actual
reported interview questions for the company from Glassdoor mirrors,
Reddit threads, and the company's own engineering-interview blog posts.

Triggered when `settings.enable_managed_likely_questions=True`.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..config import settings
from ..llm import call_with_tools
from ..prompts import load_prompt
from ..schemas import (
    CareerEntry,
    ExtractedJobDescription,
    LikelyQuestionsOutput,
    ResearchBundle,
    UserProfile,
)
from ..server_tools import WEB_FETCH, WEB_SEARCH
from ..validators.banned_phrases import contains_banned
from . import _register_session

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT_BASE = load_prompt("likely_questions")
_LIVE_ADDENDUM = """

## Managed live-research mode (enable_managed_likely_questions=True)

You have Web Search and Web Fetch tools. Before predicting, do up to
2 targeted lookups for actual reported interview experience:
  - "<company name> interview experience site:reddit.com"
  - "<company name> interview questions" (Glassdoor mirrors / blog)

Hard cap: 2 lookups. Move on; the in-bundle JD + company_research
covers most of what you need.

For each lookup, capture the verbatim phrasing of any specific question
ACTUALLY ASKED at this company. Prefer quotes over generic categories.

CRITICAL — Output structure:

The LikelyQuestionsOutput JSON you emit MUST have 8-12 entries in
the `questions` field, and EACH entry must have a non-empty
`citations` list (a list of Citation objects).

Two valid Citation shapes:
  {"kind": "url_snippet", "url": "https://...", "verbatim_snippet": "..."}
  {"kind": "career_entry", "entry_id": "<from career_entries>"}

A url_snippet's verbatim_snippet must appear character-for-character
on the fetched page. Empty citations on any question = failed output.

Quality bar: a "predicted" question rooted in a real Glassdoor/Reddit
report is far more useful than an inferred one. Lean on real data.
"""

SYSTEM_PROMPT = _SYSTEM_PROMPT_BASE + _LIVE_ADDENDUM


async def run(
    *,
    jd: ExtractedJobDescription,
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
    session_id: Optional[str] = None,
) -> LikelyQuestionsOutput:
    """Live-web-equipped interview question prediction."""

    company = research_bundle.company_research

    user_input = json.dumps({
        "role": jd.role_title,
        "seniority": jd.seniority_signal,
        "company": company.company_name,
        "company_domain": company.company_domain,
        "jd_required_skills": jd.required_skills,
        "jd_specificity_signals": jd.specificity_signals[:5],
        "tech_stack_signals": company.tech_stack_signals[:5],
        "user_motivations": user.motivations[:5],
        "career_entries": [
            {"entry_id": e.entry_id, "kind": e.kind, "text": e.raw_text[:300]}
            for e in retrieved_entries[:8]
        ],
        "instruction": (
            "Use Web Search to pull real reported interview questions "
            "for this company before predicting. 8-12 questions, each "
            "cited."
        ),
    }, default=str)

    def _pv(out: LikelyQuestionsOutput) -> list[str]:
        problems: list[str] = []
        if len(out.questions) < 6:
            problems.append(
                f"only {len(out.questions)} questions; need 8-12."
            )
        no_cites = [i for i, q in enumerate(out.questions) if not q.citations]
        if no_cites:
            problems.append(
                f"questions[{no_cites[:3]}] have empty citations. "
                "Every question needs >=1 Citation."
            )
        return problems

    out = await call_with_tools(
        agent_name="likely_questions_managed",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=LikelyQuestionsOutput,
        server_tools=[WEB_SEARCH, WEB_FETCH],
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
        post_validate=_pv,
    )

    # Banned-phrase post-validation (parity with in-process variant).
    for q in out.questions:
        for p in contains_banned(q.question):
            logger.warning(
                "likely_questions_managed banned phrase in question: %s", p,
            )
        for p in contains_banned(q.strategy_note):
            logger.warning(
                "likely_questions_managed banned phrase in strategy_note: %s", p,
            )

    logger.info(
        "likely_questions_managed: questions=%d", len(out.questions),
    )
    return out


_register_session("likely_questions_managed", run)
