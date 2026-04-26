"""Telegram message handlers.

One handler per intent. The on_message dispatcher routes via IntentRouter.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

import pydantic
from telegram import Message, Update
from telegram.ext import ContextTypes

from ..config import settings
from ..observability import bind_request_id, new_request_id
from ..orchestrator import (
    handle_analyse_offer,
    handle_draft_cover_letter,
    handle_draft_cv,
    handle_draft_reply,
    handle_forward_job,
    handle_full_prep,
    handle_predict_questions,
    handle_salary_advice,
)
from ..ratelimit import RateLimiter
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

log = logging.getLogger(__name__)


def get_storage(context: ContextTypes.DEFAULT_TYPE) -> Storage:
    return context.bot_data["storage"]


def get_rate_limiter(context: ContextTypes.DEFAULT_TYPE) -> RateLimiter:
    """Lazy singleton — constructed on first access per bot process."""
    limiter = context.bot_data.get("rate_limiter")
    if limiter is None:
        limiter = RateLimiter()
        context.bot_data["rate_limiter"] = limiter
    return limiter


def get_user_id(update: Update) -> str:
    return str(update.effective_user.id)


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point: greet returning user or point newcomers to the web.

    Wave 10 of the dual-surface migration (MIGRATION_PLAN.md ADR-003)
    moved onboarding to the web wizard. Telegram no longer runs its
    own onboarding flow — un-onboarded users get a redirect link
    instead. The legacy in-memory session dict + handler were
    deleted in PROCESS Entry 47.
    """
    storage = get_storage(context)
    user_id = get_user_id(update)

    existing = await storage.get_user_profile(user_id)
    if existing:
        await update.message.reply_text(
            "Welcome back. Forward me a job URL and I'll run the full check."
        )
        return

    await update.message.reply_text(
        "👋 Welcome to Trajectory.\n\n"
        "Set up your profile on the web app first:\n"
        f"{settings.web_url}\n\n"
        "Takes a few minutes. Come back here to forward job URLs."
    )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main dispatcher — gates onboarding, then routes by intent."""
    # D1: every Telegram message gets its own request_id so log lines
    # from Phase 1 agents, retries, and shield calls can be correlated
    # back to one user turn. contextvars propagate through asyncio.gather.
    bind_request_id(new_request_id())

    chat_id = update.effective_chat.id
    user_id = get_user_id(update)
    storage = get_storage(context)
    text = update.message.text or ""

    # ── PDF document fast-path: forwarded offer letters ───────────────────
    # PROCESS Entry 43, Workstream F. A document with mime_type
    # "application/pdf" (offer letter, contract) routes directly to the
    # analyse_offer pipeline, bypassing the intent router. The user's
    # caption (if any) is treated as additional context.
    document = getattr(update.message, "document", None)
    if document is not None and (
        getattr(document, "mime_type", "") == "application/pdf"
        or (getattr(document, "file_name", "") or "").lower().endswith(".pdf")
    ):
        user = await storage.get_user_profile(user_id)
        if not user:
            await update.message.reply_text(
                "Set up your profile on the web app first:\n"
                f"{settings.web_url}"
            )
            return
        try:
            await _handle_analyse_offer_pdf(update, context, user, storage, document)
        except ContentIntegrityRejected as exc:
            log.warning("Content shield rejected offer PDF: %s", exc.verdict.reasoning)
            await update.message.reply_text(
                "I couldn't process this offer letter — content integrity check failed."
            )
        except Exception as exc:
            await _handle_handler_exception(update, "analyse_offer", exc)
        return

    # ── Check profile exists ───────────────────────────────────────────────
    user = await storage.get_user_profile(user_id)
    if not user:
        await update.message.reply_text(
            "Set up your profile on the web app first:\n"
            f"{settings.web_url}\n\n"
            "Come back here to forward job URLs once you're done."
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

    # ── Rate limit ────────────────────────────────────────────────────────
    if settings.enforce_rate_limit:
        decision = get_rate_limiter(context).check(user_id, intent)
        if not decision.allowed:
            wait = max(1, int(decision.retry_after_s + 0.5))
            await update.message.reply_text(
                f"Slow down — try again in {wait}s. "
                "(Rate limit on {category} calls.)".format(
                    category=decision.category
                )
            )
            return

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
        elif intent == "analyse_offer":
            # Text-pasted offer letter (no PDF document attached). The
            # PDF fast-path is handled above before intent routing.
            await _handle_analyse_offer_text(update, context, user, storage, text, last_session)
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
        await _handle_handler_exception(update, intent, exc)


def _is_transient_error(exc: BaseException) -> bool:
    """Network / upstream-5xx / sqlite-busy / our own timeouts.

    Kept as a free function so tests can monkeypatch around the
    anthropic import on bare CI environments.
    """
    if isinstance(exc, (asyncio.TimeoutError, sqlite3.OperationalError)):
        return True
    try:
        import anthropic  # type: ignore

        if isinstance(exc, anthropic.APIConnectionError):
            return True
        if isinstance(exc, anthropic.APIStatusError):
            status = getattr(exc, "status_code", None)
            return isinstance(status, int) and status >= 500
    except Exception:  # pragma: no cover
        pass
    return False


def _is_user_input_error(exc: BaseException) -> bool:
    """Malformed input — missing URL, bad onboarding fields, etc."""
    if isinstance(exc, (ValueError, pydantic.ValidationError)):
        return True
    return False


async def _handle_handler_exception(
    update: Update, intent: str, exc: BaseException
) -> None:
    """Classify + reply. Fire-and-forget; never raises."""
    if isinstance(exc, RendererEmptyOutput):
        log.error("Renderer empty-output for intent %s: %r", intent, exc)
        await update.message.reply_text(
            "I generated the content but the file came back empty — "
            "an internal bug. Type /recent to try again, or message me "
            "for the text version."
        )
        return
    if isinstance(exc, DocumentDeliveryFailed):
        log.warning("Document delivery failed for intent %s: %r", intent, exc)
        await update.message.reply_text(
            "I built the file but couldn't deliver it over Telegram. "
            "Type /recent to try again — the generated text was already "
            "sent in the previous message."
        )
        return
    if _is_transient_error(exc):
        log.warning(
            "Transient error on intent %s: %r", intent, exc,
        )
        await update.message.reply_text(
            "Network hiccup on my side — try again in ~30s. "
            "If it keeps failing, forward a fresh job URL."
        )
        return
    if _is_user_input_error(exc):
        log.info(
            "User-input error on intent %s: %r", intent, exc,
        )
        await update.message.reply_text(
            "I couldn't parse that — rephrase or include a job URL, "
            "and I'll try again."
        )
        return
    log.exception("Handler error for intent %s: %s", intent, exc)
    await update.message.reply_text(
        "Something went wrong on my end — the issue has been logged. "
        "Try again, or forward a new job URL."
    )


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
    from ..orchestrator import PHASE_1_AGENTS
    from ..progress import TelegramEmitter
    from .formatting import format_phase1_progress
    from .progress_stream import PhaseOneProgressStreamer

    progress_text = format_phase1_progress(
        completed_agents=[], all_agents=PHASE_1_AGENTS,
    )
    progress_msg = await update.message.reply_html(progress_text)

    streamer = PhaseOneProgressStreamer(
        bot=context.bot,
        chat_id=update.effective_chat.id,
        message_id=progress_msg.message_id,
        all_agents=PHASE_1_AGENTS,
    )
    emitter = TelegramEmitter(streamer)

    try:
        bundle, verdict = await handle_forward_job(
            job_url=job_url,
            user=user,
            session=session,
            storage=storage,
            emitter=emitter,
        )
        await emitter.close()

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


class RendererEmptyOutput(RuntimeError):
    """Renderer returned None or wrote a zero-byte file.

    Distinct from a Telegram network error — the CV/cover letter never
    reached the wire in the first place. Bot surfaces a different
    message so the user knows to retry from scratch vs retry send.
    """


class DocumentDeliveryFailed(RuntimeError):
    """send_document failed (Telegram BadRequest/NetworkError).

    File was rendered fine — the delivery hop broke. User sees a
    "couldn't deliver, type /recent to retry" message so they don't
    assume generation itself failed.
    """


async def _send_document(
    context, chat_id: int, path, *, filename: Optional[str] = None
) -> None:
    """Send a file without leaking the file handle.

    python-telegram-bot v21's `send_document` accepts a pathlib.Path (it
    opens + closes internally). Passing a bare `open()` leaked descriptors
    on every CV/cover-letter request.

    Raises `RendererEmptyOutput` when the path is None, missing, or
    empty. Raises `DocumentDeliveryFailed` on Telegram transport error.
    Both surface to the bot-level dispatcher as specific user messages.
    """
    if path is None or not path.exists() or path.stat().st_size == 0:
        raise RendererEmptyOutput(
            f"renderer produced no file at {path!r}"
        )
    try:
        await context.bot.send_document(
            chat_id,
            document=path,
            filename=filename,
        )
    except Exception as exc:
        # Telegram's error types live behind telegram.error; catch
        # broadly and wrap so callers don't import telegram internals.
        log.warning("send_document failed for %s: %r", path, exc)
        raise DocumentDeliveryFailed(
            f"Telegram rejected document {filename or path}: {exc}"
        ) from exc


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
        # cv_latex_pdf is optional (additive third path — None when
        # pdflatex is missing or the LaTeX render failed). Including
        # it in the loop sends it after the docx + reportlab pdf when
        # present and is a no-op otherwise.
        for key in ("cv_docx", "cv_pdf", "cv_latex_pdf"):
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


# ---------------------------------------------------------------------------
# Offer analysis (PROCESS Entry 43, Workstream F)
# ---------------------------------------------------------------------------


def _format_offer_analysis(analysis) -> str:
    """Pretty-print an OfferAnalysis as a single Telegram message."""
    lines: list[str] = [f"📄 *Offer analysis: {analysis.company_name}*"]
    if analysis.role_title:
        lines.append(f"Role: {analysis.role_title}")
    lines.append("")

    def _comp(label: str, c) -> None:
        if c is not None:
            lines.append(f"• *{label}*: {c.value_text}")

    _comp("Base salary", analysis.base_salary_gbp)
    _comp("Bonus", analysis.bonus)
    _comp("Equity", analysis.equity)
    _comp("Notice period", analysis.notice_period)
    _comp("Non-compete", analysis.non_compete)
    _comp("IP assignment", analysis.ip_assignment)
    if analysis.benefits:
        lines.append("• *Benefits*:")
        for b in analysis.benefits:
            lines.append(f"  – {b.value_text}")
    if analysis.unusual_clauses:
        lines.append("\n*Unusual clauses to flag:*")
        for u in analysis.unusual_clauses:
            lines.append(f"⚠️ {u.label}: {u.value_text}")
    if analysis.market_comparison_note:
        lines.append(f"\n*Market comparison:* {analysis.market_comparison_note}")
    if analysis.flags:
        lines.append("\n*Flags:*")
        for f in analysis.flags:
            lines.append(f"🚩 {f}")
    return "\n".join(lines)


async def _handle_analyse_offer_pdf(update, context, user, storage, document):
    """Fast-path: user forwarded a PDF offer letter."""
    log.info("analyse_offer (PDF): user=%s file=%s", user.user_id, document.file_name)
    await update.message.reply_text(
        "Analysing the offer letter… this takes ~30-60s for a typical PDF."
    )

    # Download the PDF bytes via Telegram's file API.
    tg_file = await document.get_file()
    pdf_bytes_io = await tg_file.download_as_bytearray()
    pdf_bytes = bytes(pdf_bytes_io)

    # Use the most recent session's bundle for market comparison if any.
    recent = await storage.get_recent_sessions(user.user_id, limit=1)
    session = recent[0] if recent else None

    analysis = await handle_analyse_offer(
        user=user,
        storage=storage,
        session=session,
        pdf_bytes=pdf_bytes,
    )
    await update.message.reply_markdown(_format_offer_analysis(analysis))


async def _handle_analyse_offer_text(update, context, user, storage, text, last_session):
    """Slow-path: user pasted the offer letter as text."""
    log.info("analyse_offer (text): user=%s len=%d", user.user_id, len(text))
    await update.message.reply_text(
        "Analysing the pasted offer text… this takes ~20-40s."
    )
    analysis = await handle_analyse_offer(
        user=user,
        storage=storage,
        session=last_session,
        text_pasted=text,
    )
    await update.message.reply_markdown(_format_offer_analysis(analysis))
