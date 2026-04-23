"""Telegram message handlers.

One handler per intent. The on_message dispatcher routes via IntentRouter.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from telegram import Message, Update
from telegram.ext import ContextTypes

from ..orchestrator import (
    handle_draft_cover_letter,
    handle_draft_cv,
    handle_draft_reply,
    handle_forward_job,
    handle_full_prep,
    handle_predict_questions,
    handle_salary_advice,
)
from ..validators.content_shield import ContentIntegrityRejected
from ..schemas import Session
from ..storage import Storage
from .formatting import (
    format_cover_letter,
    format_cv_output,
    format_likely_questions,
    format_salary_recommendation,
    format_verdict,
)
from .onboarding import OnboardingSession, OnboardingState, finalise_onboarding

log = logging.getLogger(__name__)

# In-memory onboarding sessions (single-user demo)
_onboarding_sessions: dict[int, OnboardingSession] = {}


def get_storage(context: ContextTypes.DEFAULT_TYPE) -> Storage:
    return context.bot_data["storage"]


def get_user_id(update: Update) -> str:
    return str(update.effective_user.id)


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point: begin onboarding or greet returning user."""
    storage = get_storage(context)
    user_id = get_user_id(update)
    chat_id = update.effective_chat.id

    existing = await storage.get_user_profile(user_id)
    if existing:
        await update.message.reply_text(
            f"Welcome back. Forward me a job URL and I'll run the full check."
        )
        return

    # Start onboarding. Capture the user's Telegram display name so the
    # profile doesn't end up with the "User" placeholder — we never ask
    # for a name explicitly during the 7-stage flow, so this is the
    # only clean way to populate it.
    ob = OnboardingSession(user_id=user_id)
    tg_user = update.effective_user
    if tg_user is not None:
        first = (tg_user.first_name or "").strip()
        last = (tg_user.last_name or "").strip()
        full = (first + " " + last).strip() or (tg_user.username or "")
        if full:
            ob.display_name = full
    _onboarding_sessions[chat_id] = ob
    ob.state = OnboardingState.CAREER

    await update.message.reply_text(
        "Hi — I'm Trajectory, your UK job-search assistant.\n\n"
        "I need about 5 minutes to set up your profile. "
        "After that, forward me any job and I'll tell you whether to bother applying.\n\n"
        + ob.current_prompt()
    )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main dispatcher — gates onboarding, then routes by intent."""
    chat_id = update.effective_chat.id
    user_id = get_user_id(update)
    storage = get_storage(context)
    text = update.message.text or ""

    # ── Onboarding gate ───────────────────────────────────────────────────
    if chat_id in _onboarding_sessions:
        ob = _onboarding_sessions[chat_id]
        if ob.is_collecting() or ob.state == OnboardingState.START:
            await _handle_onboarding_message(update, context, ob, storage)
            return

    # ── Check profile exists ───────────────────────────────────────────────
    user = await storage.get_user_profile(user_id)
    if not user:
        await update.message.reply_text(
            "Use /start to set up your profile first."
        )
        return

    # ── Intent routing ────────────────────────────────────────────────────
    from ..sub_agents.intent_router import route as route_intent

    recent_sessions = await storage.get_recent_sessions(user_id, limit=4)
    recent_msgs: list[str] = []
    last_session: Optional[Session] = recent_sessions[0] if recent_sessions else None

    routed = await route_intent(
        user_message=text,
        recent_messages=recent_msgs,
        last_session=last_session,
    )

    if routed.blocked_by_verdict:
        if last_session and last_session.verdict:
            # Session.verdict is always a Verdict model — storage.save_verdict
            # coerces on the write side, so readers don't need isinstance()
            # branches here.
            for chunk in format_verdict(last_session.verdict):
                await update.message.reply_html(chunk)
        else:
            await update.message.reply_text("Last verdict was NO_GO — I won't generate a pack for that role.")
        return

    if routed.confidence == "LOW" and routed.intent != "chitchat":
        await update.message.reply_text(
            f"I wasn't sure what you meant. Did you want to {routed.intent.replace('_', ' ')}? "
            "Reply with more details or a job URL."
        )
        return

    intent = routed.intent

    try:
        if intent == "forward_job":
            await _handle_forward_job(update, context, user, storage, routed)
        elif intent == "draft_cv":
            await _handle_draft_cv(update, context, user, storage, last_session)
        elif intent == "draft_cover_letter":
            await _handle_draft_cover_letter(update, context, user, storage, last_session)
        elif intent == "predict_questions":
            await _handle_predict_questions(update, context, user, storage, last_session)
        elif intent == "salary_advice":
            await _handle_salary_advice(update, context, user, storage, last_session)
        elif intent == "full_prep":
            await _handle_full_prep(update, context, user, storage, last_session)
        elif intent == "draft_reply":
            await _handle_draft_reply(update, context, user, storage, text)
        elif intent == "profile_query":
            await _handle_profile_query(update, context, user, storage)
        elif intent == "profile_edit":
            await update.message.reply_text(
                "Profile edits aren't wired to a UI yet. "
                "Tell me what to change and I'll note it."
            )
        elif intent == "recent":
            await _handle_recent(update, context, user, storage)
        else:
            await update.message.reply_text(
                "Got it. Forward me a job URL when you're ready, "
                "or ask for a CV, cover letter, interview questions, or salary advice."
            )
    except ContentIntegrityRejected as exc:
        log.warning(
            "Content shield rejected %s for intent %s: %s",
            exc.source_type, intent, exc.verdict.reasoning,
        )
        await update.message.reply_text(
            "I couldn't process this content — there were signs of prompt "
            "injection. The job URL may be compromised or the page was modified."
        )
    except Exception as exc:
        log.exception("Handler error for intent %s: %s", intent, exc)
        await update.message.reply_text(
            "Something went wrong. Try again, or forward a new job URL."
        )


# ---------------------------------------------------------------------------
# Onboarding message handler
# ---------------------------------------------------------------------------


async def _handle_onboarding_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    ob: OnboardingSession,
    storage: Storage,
) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text or ""

    # Show a typing indicator — parsing each reply costs a short Opus 4.7
    # low-effort round-trip, so the user shouldn't think the bot hung.
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    outcome = await ob.advance(text)

    # abandon_session: too many off-topic replies across the session.
    # Drop the onboarding entry so the next /start gets a clean session
    # and let the user know they need to restart.
    if outcome.abandon_session:
        _onboarding_sessions.pop(chat_id, None)
        if outcome.follow_up:
            await update.message.reply_text(outcome.follow_up)
        return

    # needs_clarification or off_topic: stay on the current stage, send
    # the one-line follow-up, wait for the user to try again.
    if outcome.follow_up:
        await update.message.reply_text(outcome.follow_up)
        return

    if outcome.state == OnboardingState.PROCESSING:
        msg = await update.message.reply_text("Processing your profile — one moment…")
        try:
            user = await finalise_onboarding(ob, storage)
            del _onboarding_sessions[chat_id]
            ob.state = OnboardingState.DONE
            await msg.edit_text(
                f"Profile ready. Forward me a job URL and I'll run the checks."
            )
        except Exception as exc:
            log.exception("Onboarding finalisation failed: %s", exc)
            await msg.edit_text(
                "Couldn't process your profile. Type /start to try again."
            )
        return

    prompt = ob.next_prompt()
    if prompt:
        await update.message.reply_text(prompt)


# ---------------------------------------------------------------------------
# Intent handlers
# ---------------------------------------------------------------------------


async def _handle_forward_job(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    storage: Storage,
    routed,
) -> None:
    job_url = (routed.job_url_ref or routed.extracted_params.get("job_url") or update.message.text or "").strip()
    if not job_url.startswith("http"):
        await update.message.reply_text("Paste a job URL and I'll run the full check.")
        return

    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session = Session(
        session_id=session_id,
        user_id=user.user_id,
        intent="forward_job",
        job_url=job_url,
        created_at=now,
    )
    await storage.save_session(session)

    # Send progress message
    from .formatting import format_phase1_progress
    all_agents = [
        "phase_1_jd_extractor",
        "phase_1_company_scraper_summariser",
        "companies_house",
        "reviews",
        "phase_1_ghost_job_jd_scorer",
        "salary_data",
        "sponsor_register",
        "soc_check",
        "phase_1_red_flags",
    ]
    progress_text = format_phase1_progress(completed_agents=[], all_agents=all_agents)
    progress_msg = await update.message.reply_html(progress_text)

    try:
        bundle, verdict = await handle_forward_job(
            job_url=job_url,
            user=user,
            session=session,
            storage=storage,
            bot=context.bot,
            chat_id=update.effective_chat.id,
            message_id=progress_msg.message_id,
        )

        for chunk in format_verdict(verdict):
            await update.message.reply_html(chunk)

        if verdict.decision == "GO":
            await update.message.reply_text(
                "What do you want next?\n"
                "• CV tailored to this role\n"
                "• Cover letter\n"
                "• Interview questions\n"
                "• Salary strategy\n"
                "• Full pack (all of the above)\n\n"
                "Just tell me."
            )
    except Exception as exc:
        log.exception("forward_job failed: %s", exc)
        # Do not echo raw exception text to Telegram — may leak tokens,
        # file paths, or internal config. Server-side log carries the detail.
        await update.message.reply_text(
            "Research failed. Double-check the URL is public, or try again."
        )


async def _require_session(
    update: Update,
    last_session: Optional[Session],
    storage: Storage,
    label: str,
) -> Optional[Session]:
    if not last_session:
        await update.message.reply_text(
            f"Forward a job URL first, then ask for {label}."
        )
        return None
    return last_session


async def _send_document(context, chat_id: int, path, *, filename: Optional[str] = None) -> None:
    """Send a file without leaking the file handle.

    python-telegram-bot v21's `send_document` accepts a pathlib.Path (it
    opens + closes internally). Passing a bare `open()` leaked descriptors
    on every CV/cover-letter request.
    """
    await context.bot.send_document(
        chat_id,
        document=path,
        filename=filename,
    )


async def _handle_draft_cv(update, context, user, storage, last_session):
    session = await _require_session(update, last_session, storage, "a CV")
    if not session:
        return
    msg = await update.message.reply_text("Tailoring your CV…")
    cv, docx_path, pdf_path, latex_pdf_path = await handle_draft_cv(
        session, user, storage,
    )
    await msg.delete()
    for chunk in format_cv_output(cv):
        await update.message.reply_html(chunk)
    chat_id = update.effective_chat.id
    await _send_document(context, chat_id, docx_path, filename=docx_path.name)
    await _send_document(context, chat_id, pdf_path, filename=pdf_path.name)
    if latex_pdf_path is not None:
        # Additive third attachment — LaTeX-typeset PDF, optional.
        await _send_document(
            context, chat_id, latex_pdf_path,
            filename=latex_pdf_path.name,
        )


async def _handle_draft_cover_letter(update, context, user, storage, last_session):
    session = await _require_session(update, last_session, storage, "a cover letter")
    if not session:
        return
    msg = await update.message.reply_text("Writing your cover letter…")
    cl, docx_path, pdf_path = await handle_draft_cover_letter(session, user, storage)
    await msg.delete()
    for chunk in format_cover_letter(cl):
        await update.message.reply_html(chunk)
    chat_id = update.effective_chat.id
    await _send_document(context, chat_id, docx_path, filename=docx_path.name)
    await _send_document(context, chat_id, pdf_path, filename=pdf_path.name)


async def _handle_predict_questions(update, context, user, storage, last_session):
    session = await _require_session(update, last_session, storage, "interview questions")
    if not session:
        return
    msg = await update.message.reply_text("Predicting interview questions…")
    lq = await handle_predict_questions(session, user, storage)
    await msg.delete()
    for chunk in format_likely_questions(lq):
        await update.message.reply_html(chunk)


async def _handle_salary_advice(update, context, user, storage, last_session):
    session = await _require_session(update, last_session, storage, "salary advice")
    if not session:
        return
    msg = await update.message.reply_text("Building your salary strategy…")
    sal = await handle_salary_advice(session, user, storage)
    await msg.delete()
    for chunk in format_salary_recommendation(sal):
        await update.message.reply_html(chunk)


async def _handle_full_prep(update, context, user, storage, last_session):
    session = await _require_session(update, last_session, storage, "a full pack")
    if not session:
        return
    msg = await update.message.reply_text(
        "Generating full application pack — CV, cover letter, interview questions, salary strategy…"
    )
    pack, files = await handle_full_prep(session, user, storage)
    await msg.delete()

    chat_id = update.effective_chat.id

    if pack.cv:
        for chunk in format_cv_output(pack.cv):
            await update.message.reply_html(chunk)
        for key in ("cv_docx", "cv_pdf"):
            p = files.get(key)
            if p:
                await _send_document(context, chat_id, p, filename=p.name)

    if pack.cover_letter:
        for chunk in format_cover_letter(pack.cover_letter):
            await update.message.reply_html(chunk)
        for key in ("cover_letter_docx", "cover_letter_pdf"):
            p = files.get(key)
            if p:
                await _send_document(context, chat_id, p, filename=p.name)

    if pack.likely_questions:
        for chunk in format_likely_questions(pack.likely_questions):
            await update.message.reply_html(chunk)

    if pack.salary:
        for chunk in format_salary_recommendation(pack.salary):
            await update.message.reply_html(chunk)


async def _handle_draft_reply(update, context, user, storage, text):
    # Note: storage.get_writing_style_profile is keyed on user_id (the
    # module-level SELECT uses WHERE user_id = ?). Passing the
    # writing_style_profile_id here previously caused a silent miss —
    # we look up by user_id inside orchestrator.handle_draft_reply
    # regardless, so this block is retained only for symmetry/logging.
    reply = await handle_draft_reply(
        incoming_message=text,
        user_intent="other",
        user=user,
        storage=storage,
    )
    await update.message.reply_html(
        f"<b>Short:</b>\n{reply.short_variant}\n\n<b>Longer:</b>\n{reply.long_variant}"
    )


async def _handle_profile_query(update, context, user, storage):
    entries = await storage.retrieve_relevant_entries(
        user_id=user.user_id,
        query=update.message.text or "profile",
        k=5,
    )
    if not entries:
        await update.message.reply_text("Nothing relevant in your profile yet.")
        return
    lines = [f"• {e.kind}: {e.raw_text[:120]}" for e in entries]
    await update.message.reply_text("\n".join(lines))


async def _handle_recent(update, context, user, storage):
    sessions = await storage.get_recent_sessions(user.user_id, limit=5)
    if not sessions:
        await update.message.reply_text("No recent sessions.")
        return
    lines = []
    for s in sessions:
        verdict_str = ""
        if s.verdict:
            v = s.verdict
            decision = v.get("decision", "?") if isinstance(v, dict) else v.decision
            verdict_str = f" — {decision}"
        lines.append(f"• {s.intent}: {s.job_url or '(no URL)'}{verdict_str}")
    await update.message.reply_text("\n".join(lines))
