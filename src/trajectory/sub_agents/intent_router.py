"""Intent Router — classifies every user message into one of 11 intents.

System prompt verbatim from AGENTS.md §1.
Model: Opus 4.7 xhigh (misroute is costly).
"""

from __future__ import annotations

from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import IntentRouterOutput, Session

SYSTEM_PROMPT = """\
You route user messages in Trajectory, a UK job-search personal assistant.

Every message resolves to exactly one of these 11 intents:

1. forward_job        - user pasted or forwarded a job URL or posting
2. draft_cv           - user wants a CV tailored to a specific role
3. draft_cover_letter - user wants a cover letter for a role
4. predict_questions  - user wants likely interview questions for a role
5. salary_advice      - user wants salary guidance for a role or situation
6. draft_reply        - user wants help replying to a recruiter/email
7. full_prep          - user wants the complete application pack for a role
8. profile_query      - user is asking about their own history or profile
9. profile_edit       - user is updating their profile (prefs, floor, visa status)
10. recent            - user asking about recent sessions / job history
11. chitchat          - everything else: greetings, thanks, small talk, unclear

RULES:

1. When the user pastes a URL or references "this job", resolve against
   the most recent forward_job session unless they specify otherwise.
   Set job_url_ref accordingly.

2. If the user references a specific company by name without a URL and
   no recent session exists, classify as the most appropriate generator
   intent but set job_url_ref=null and missing_context=true.

3. Chitchat is the fall-through. When in doubt, classify as chitchat
   and let the handler produce a brief clarifying reply. Never
   misclassify to force a pipeline.

4. "Forward me a job" / "here's a link" / direct URL paste -> forward_job.

5. Never route to a Phase 4 generator (3-7) when the last verdict was
   NO_GO. Set blocked_by_verdict=true.

6. Never invent intents outside the 11 listed.

OUTPUT: Valid JSON matching the IntentRouterOutput schema. No prose.
"""


async def route(
    user_message: str,
    recent_messages: list[str],
    last_session: Optional[Session] = None,
    session_id: Optional[str] = None,
) -> IntentRouterOutput:
    context_lines = [f"USER MESSAGE: {user_message}"]
    if recent_messages:
        context_lines.append("RECENT CONTEXT (last 4 messages):")
        context_lines.extend(f"  {m}" for m in recent_messages[-4:])
    if last_session:
        verdict_status = "NO_GO"
        if last_session.verdict:
            verdict_status = last_session.verdict.get("decision", "unknown") if isinstance(last_session.verdict, dict) else last_session.verdict.decision
        context_lines.append(
            f"LAST SESSION: job_url={last_session.job_url}, "
            f"intent={last_session.intent}, "
            f"verdict={verdict_status}"
        )

    return await call_agent(
        agent_name="intent_router",
        system_prompt=SYSTEM_PROMPT,
        user_input="\n".join(context_lines),
        output_schema=IntentRouterOutput,
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
    )
