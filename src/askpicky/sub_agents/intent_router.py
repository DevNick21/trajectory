"""Intent Router — classifies every user message into one of the 12 intents.

Two-tier:
  - **Tier 0** (this file): deterministic URL + keyword rules. Catches
    ~80% of messages with zero LLM cost (~1ms). The remaining 20%
    fall through to:
  - **Tier 1**: Haiku via `call_agent`. System prompt from AGENTS.md §1.

Model downgrade 2026-05-22: tier-1 dropped from Sonnet to Haiku.
12-way classification + the user has already pre-filtered ~80%
deterministically — Haiku handles the rest cleanly.
"""

from __future__ import annotations

import re
from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..prompts import load_prompt
from ..schemas import IntentRouterOutput, Session

SYSTEM_PROMPT = load_prompt("intent_router")


# ---------------------------------------------------------------------------
# Tier 0 — deterministic rules. ~1ms. No LLM.
# ---------------------------------------------------------------------------


# Any http/https URL with a typical job-board / careers-page shape.
# `forward_job` is the highest-confidence pattern — when a URL is in
# the message, it's almost always either "look at this role" or a
# share. We capture the URL into job_url_ref directly.
_URL_RE = re.compile(r"https?://[^\s<>'\"]+")

# Strong keyword anchors per intent. Lowercased + matched on whole
# words. Order matters: first match wins. Phrases-most-specific-first.
_KEYWORD_RULES: list[tuple[str, list[re.Pattern]]] = [
    ("draft_cv", [
        re.compile(r"\b(?:draft|write|generate|tailor|update|make|build|create)\s+(?:me\s+)?(?:an?\s+|my\s+)?cv\b", re.IGNORECASE),
        re.compile(r"\bcv\s+(?:for|tailored|tailor)\b", re.IGNORECASE),
        re.compile(r"\b(?:tailored|tailor\s+my)\s+cv\b", re.IGNORECASE),
    ]),
    ("draft_cover_letter", [
        re.compile(r"\b(?:draft|write|generate|make)\s+(?:me\s+)?(?:an?\s+|my\s+)?cover\s*letter\b", re.IGNORECASE),
        re.compile(r"\bcover\s*letter\s+(?:for|please)\b", re.IGNORECASE),
    ]),
    ("salary_advice", [
        re.compile(r"\bsalary\s+(?:advice|guidance|negotiation|target|range|expectation)\b", re.IGNORECASE),
        re.compile(r"\b(?:what|how\s+much)\s+(?:should\s+i\s+ask|to\s+ask)\s+for\b", re.IGNORECASE),
        re.compile(r"\bnegotiate\s+(?:my\s+)?(?:salary|offer|pay)\b", re.IGNORECASE),
        re.compile(r"\b(?:fair|good|market)\s+salary\b", re.IGNORECASE),
    ]),
    ("draft_reply", [
        re.compile(r"\b(?:draft|write|help\s+me\s+(?:reply|respond))\s+(?:a\s+)?(?:reply|response)\b", re.IGNORECASE),
        re.compile(r"\breply\s+to\s+(?:this|the)\s+(?:recruiter|email|message)\b", re.IGNORECASE),
        re.compile(r"\brespond\s+to\s+(?:this|the)\s+(?:recruiter|email|message)\b", re.IGNORECASE),
    ]),
    ("predict_questions", [
        re.compile(r"\b(?:predict|guess|what|likely)\s+(?:interview\s+)?questions\b", re.IGNORECASE),
        re.compile(r"\binterview\s+(?:prep|preparation|questions)\b", re.IGNORECASE),
        re.compile(r"\bwhat\s+(?:will|might)\s+they\s+ask\b", re.IGNORECASE),
    ]),
    ("full_prep", [
        re.compile(r"\bfull\s+(?:prep|pack|preparation|package)\b", re.IGNORECASE),
        re.compile(r"\b(?:do|run|generate)\s+everything\b", re.IGNORECASE),
        re.compile(r"\bgive\s+me\s+everything\b", re.IGNORECASE),
    ]),
    ("analyse_offer", [
        re.compile(r"\b(?:analyse|analyze|review|look\s+at)\s+(?:this|my|the)\s+offer\b", re.IGNORECASE),
        re.compile(r"\boffer\s+(?:letter|analysis)\b", re.IGNORECASE),
    ]),
    ("profile_query", [
        re.compile(r"\b(?:what|tell\s+me)\s+(?:do\s+you\s+know|about)\s+(?:about\s+)?me\b", re.IGNORECASE),
        re.compile(r"\bmy\s+(?:profile|history|background)\b", re.IGNORECASE),
    ]),
    ("profile_edit", [
        re.compile(r"\b(?:update|edit|change|set|modify)\s+my\s+(?:profile|salary|floor|visa|location|deal[-\s]breakers?|motivations?)\b", re.IGNORECASE),
    ]),
    ("recent", [
        re.compile(r"\b(?:recent|past|previous|last|all)\s+(?:sessions|jobs|verdicts|forwards)\b", re.IGNORECASE),
        re.compile(r"\b(?:my\s+)?(?:job\s+)?history\b", re.IGNORECASE),
        re.compile(r"\bwhat\s+(?:have\s+)?(?:i|we)\s+(?:looked\s+at|forwarded)\b", re.IGNORECASE),
    ]),
    ("compare_verdicts", [
        re.compile(r"\bcompare\s+(?:my\s+)?(?:recent\s+)?(?:verdicts|gos|jobs|roles)\b", re.IGNORECASE),
        re.compile(r"\bwhich\s+(?:role|job|verdict)\s+(?:should\s+i|to)\s+(?:apply|focus)\b", re.IGNORECASE),
        re.compile(r"\brank\s+(?:my\s+)?(?:gos|verdicts|roles)\b", re.IGNORECASE),
        re.compile(r"\bwhich\s+of\s+(?:these|my)\s+(?:gos|verdicts|roles)\b", re.IGNORECASE),
    ]),
    ("challenge_verdict", [
        re.compile(r"\b(?:are\s+you\s+sure|why\s+(?:not|no_go)|disagree|pushback)\b", re.IGNORECASE),
        re.compile(r"\b(?:i\s+think|i\s+know)\s+(?:you|they|the\s+company)\b", re.IGNORECASE),
        re.compile(r"\bbut\s+(?:they|the\s+company)\s+(?:do|have|are|is)\b", re.IGNORECASE),
        re.compile(r"\bchallenge\s+(?:this|the|that)\s+(?:verdict|decision|call)\b", re.IGNORECASE),
        re.compile(r"\breconsider\b", re.IGNORECASE),
    ]),
]

# Chitchat anchors — short greeting / acknowledgement / test messages
# get an explicit chitchat label so the bot can reply briefly without
# burning a Haiku call. Last in the chain so genuine intents above
# take precedence.
_CHITCHAT_PATTERNS = [
    re.compile(r"^\s*(?:hi|hello|hey|yo|sup|gm|good\s+(?:morning|afternoon|evening))\s*[!?.]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:thanks?|thank\s+you|ta|cheers|cool|nice|ok|okay|kk|got\s+it|noted)\s*[!?.]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:test|testing|ping)\s*[!?.]*\s*$", re.IGNORECASE),
]


def _tier0_classify(
    user_message: str, last_session: Optional[Session],
) -> Optional[IntentRouterOutput]:
    """Try to classify deterministically. None means "call the LLM"."""
    text = (user_message or "").strip()
    if not text:
        return None

    # 1. URL detection — overrides everything else. URL = forward_job.
    url_match = _URL_RE.search(text)
    if url_match:
        return IntentRouterOutput(
            intent="forward_job",
            job_url_ref=url_match.group(0),
            blocked_by_verdict=False,
            missing_context=False,
            confidence="HIGH",
            reasoning_brief="Tier-0: URL detected.",
        )

    # 2. Keyword rules — first match wins. For chained queries like
    #    "draft my CV" right after a forward, attach the last session's
    #    job_url so the orchestrator can dispatch immediately.
    for intent_name, patterns in _KEYWORD_RULES:
        for pattern in patterns:
            if pattern.search(text):
                blocked = False
                missing = False
                job_url_ref = None
                # Generator intents (3-7) need a session context. Inherit
                # from last_session when available; flag missing_context
                # when not.
                if intent_name in {
                    "draft_cv", "draft_cover_letter", "salary_advice",
                    "draft_reply", "predict_questions", "full_prep",
                }:
                    if last_session and last_session.job_url:
                        job_url_ref = last_session.job_url
                        # Verdict NO_GO blocks Phase 4 generators per
                        # AGENTS.md §1 rule 5.
                        if (
                            last_session.verdict
                            and last_session.verdict.decision == "NO_GO"
                        ):
                            blocked = True
                    else:
                        missing = True
                return IntentRouterOutput(
                    intent=intent_name,  # type: ignore[arg-type]
                    confidence="HIGH",
                    job_url_ref=job_url_ref,
                    blocked_by_verdict=blocked,
                    missing_context=missing,
                    reasoning_brief=f"Tier-0: keyword pattern matched ({intent_name}).",
                )

    # 3. Chitchat — short greeting/ack.
    for pattern in _CHITCHAT_PATTERNS:
        if pattern.match(text):
            return IntentRouterOutput(
                intent="chitchat",
                confidence="HIGH",
                job_url_ref=None,
                blocked_by_verdict=False,
                missing_context=False,
                reasoning_brief="Tier-0: chitchat pattern.",
            )

    return None  # Fall through to LLM.


# ---------------------------------------------------------------------------
# Public — try tier 0 first, escalate to LLM only when needed.
# ---------------------------------------------------------------------------


async def route(
    user_message: str,
    recent_messages: list[str],
    last_session: Optional[Session] = None,
    session_id: Optional[str] = None,
) -> IntentRouterOutput:
    # Tier 0 — deterministic. ~80% hit rate, ~1ms, $0.
    tier0 = _tier0_classify(user_message, last_session)
    if tier0 is not None:
        return tier0

    # Tier 1 — Haiku. Only fires on ambiguous messages.
    # CLAUDE.md Rule 10: user messages are untrusted — Tier 1 shield
    # only (the router only decides a label, so residual risk is capped).
    from ..validators.content_shield import shield as shield_content

    cleaned_msg, _ = await shield_content(
        content=user_message,
        source_type="user_message",
        downstream_agent="intent_router",
    )
    cleaned_recent: list[str] = []
    for m in recent_messages[-4:]:
        c, _ = await shield_content(
            content=m,
            source_type="user_message",
            downstream_agent="intent_router",
        )
        cleaned_recent.append(c)

    context_lines = [f"USER MESSAGE: {cleaned_msg}"]
    if cleaned_recent:
        context_lines.append("RECENT CONTEXT (last 4 messages):")
        context_lines.extend(f"  {m}" for m in cleaned_recent)
    if last_session:
        verdict_status = (
            last_session.verdict.decision if last_session.verdict else "NO_GO"
        )
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
        model=settings.haiku_model_id,  # downgraded 2026-05-22: tier-0 handles 80%, Haiku for the rest
        effort="medium",
        session_id=session_id,
    )
