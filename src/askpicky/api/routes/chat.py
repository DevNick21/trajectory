"""POST /api/chat — natural-language chat surface for the web (PROCESS Entry 45).

Brings the web to parity with the Telegram bot: any message you can
type to the bot now also works from the web. Internally:
  1. Run intent_router on the message
  2. Dispatch to the same handle_* the bot uses
  3. Return a single JSON response describing what happened

This is a non-streaming first pass. forward_job and full_prep have
their own SSE routes already; this endpoint short-circuits to a stub
"redirect to dedicated route" reply for those two intents and handles
the rest inline (intent_router routing decision, draft_*, salary,
draft_reply, profile_query, recent, chitchat).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ...schemas import Session, UserProfile
from ...storage import Storage
from ..dependencies import get_current_user, get_storage

router = APIRouter()
log = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    intent: str
    confidence: str
    reply_kind: str           # "text" | "redirect" | "card"
    text: Optional[str] = None
    redirect_to: Optional[str] = None    # frontend route to navigate to
    payload: Optional[dict] = None       # structured output for cards
    reasoning_brief: Optional[str] = None


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> ChatResponse:
    """Run intent_router + dispatch. Mirrors the Telegram bot's
    on_message dispatch but as a single-shot HTTP response."""
    if not req.message or not req.message.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "empty_message"},
        )

    from ...sub_agents.intent_router import route as route_intent

    recent = await storage.get_recent_sessions(user.user_id, limit=4)
    last_session: Optional[Session] = recent[0] if recent else None

    routed = await route_intent(
        user_message=req.message,
        recent_messages=[],
        last_session=last_session,
    )

    intent = routed.intent
    base = {
        "intent": intent,
        "confidence": routed.confidence,
        "reasoning_brief": routed.reasoning_brief,
    }

    # forward_job + full_prep have dedicated SSE endpoints — redirect.
    if intent == "forward_job":
        url = routed.job_url_ref or req.message.strip()
        return ChatResponse(
            **base,
            reply_kind="redirect",
            redirect_to=f"/?forward={url}",
            text=(
                f"Forwarding {url} — switching to the streaming view."
            ),
        )
    if intent == "full_prep":
        target = req.session_id or (last_session.session_id if last_session else None)
        if not target:
            return ChatResponse(
                **base, reply_kind="text",
                text="Forward a job URL first, then ask for a full pack.",
            )
        return ChatResponse(
            **base,
            reply_kind="redirect",
            redirect_to=f"/sessions/{target}",
            text="Switching to the session pack runner.",
        )

    if routed.confidence == "LOW" and intent != "chitchat":
        return ChatResponse(
            **base, reply_kind="text",
            text=(
                f"I wasn't sure what you meant. Did you want to "
                f"{intent.replace('_', ' ')}? Reply with more details."
            ),
        )

    if routed.blocked_by_verdict:
        return ChatResponse(
            **base, reply_kind="text",
            text="The last verdict was NO_GO — I won't generate a pack for that role.",
        )

    # Single-shot dispatches — return cards / text inline.
    try:
        if intent == "draft_cv":
            return _redirect_to_session(base, req.session_id, last_session,
                                        suffix="cv", label="CV")
        if intent == "draft_cover_letter":
            return _redirect_to_session(base, req.session_id, last_session,
                                        suffix="cover_letter", label="cover letter")
        if intent == "predict_questions":
            return _redirect_to_session(base, req.session_id, last_session,
                                        suffix="questions", label="interview questions")
        if intent == "salary_advice":
            return _redirect_to_session(base, req.session_id, last_session,
                                        suffix="salary", label="salary advice")
        if intent == "analyse_offer":
            return ChatResponse(
                **base, reply_kind="redirect", redirect_to="/offer",
                text="Switching to the offer analyser.",
            )
        if intent == "draft_reply":
            from ...orchestrator import handle_draft_reply
            reply = await handle_draft_reply(
                incoming_message=req.message,
                user_intent="other",  # router-extracted intent_hint goes here later
                user=user,
                storage=storage,
                session_id=req.session_id,
            )
            return ChatResponse(
                **base, reply_kind="card",
                payload={"draft_reply": reply.model_dump(mode="json")},
                text=reply.short_variant,
            )
        if intent == "profile_query":
            return ChatResponse(
                **base, reply_kind="card",
                payload={"profile": user.model_dump(mode="json")},
                text=f"Profile: {user.name} · {user.base_location} · floor £{user.salary_floor:,}",
            )
        if intent == "recent":
            return ChatResponse(
                **base, reply_kind="card",
                payload={"sessions": [s.model_dump(mode="json") for s in recent]},
                text=f"You have {len(recent)} recent session(s).",
            )
        # chitchat / fallback
        return ChatResponse(
            **base, reply_kind="text",
            text="Got it. Forward me a job URL when you're ready.",
        )
    except Exception:
        log.exception("chat dispatch failed for intent=%s", intent)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "chat_dispatch_failed"},
        )


def _redirect_to_session(
    base: dict, session_id_arg: Optional[str],
    last_session: Optional[Session],
    *, suffix: str, label: str,
) -> ChatResponse:
    sid = session_id_arg or (last_session.session_id if last_session else None)
    if not sid:
        return ChatResponse(
            **base, reply_kind="text",
            text=f"Forward a job URL first, then ask for {label}.",
        )
    return ChatResponse(
        **base, reply_kind="redirect",
        redirect_to=f"/sessions/{sid}/{suffix}",
        text=f"Opening the {label} workspace.",
    )
