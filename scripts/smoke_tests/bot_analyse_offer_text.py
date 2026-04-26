"""Smoke test — bot `analyse_offer` text path.

The PDF fast-path of analyse_offer is exercised by `bot_boot` (now
that the document=None fix landed). The TEXT path — user pastes an
offer letter as a chat message — runs through the intent router
into [_handle_analyse_offer_text] at [bot/handlers.py:658] and was
never tested. This smoke patches `orchestrator.handle_analyse_offer`
to return a synthetic `OfferAnalysis`, drives the bot handler with a
mocked update + context, and asserts:

  - reply_text fires with the "Analysing…" placeholder
  - the orchestrator was called exactly once with the pasted text
  - reply_markdown fires with the formatted analysis containing the
    company name + a flag

Cost: $0.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from ._common import (
    SmokeResult,
    build_test_session,
    build_test_user,
    prepare_environment,
    run_smoke,
)

NAME = "bot_analyse_offer_text"
REQUIRES_LIVE_LLM = False
ESTIMATED_COST_USD = 0.0


def _make_update(*, user_id: str, chat_id: int, text: str):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.message.text = text
    update.message.document = None
    update.message.reply_text = AsyncMock()
    update.message.reply_html = AsyncMock()
    update.message.reply_markdown = AsyncMock()
    return update


def _make_context(storage):
    ctx = MagicMock()
    ctx.bot_data = {"storage": storage}
    ctx.bot.send_document = AsyncMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    messages: list[str] = []
    failures: list[str] = []

    from trajectory.bot import handlers as bot_handlers
    from trajectory.schemas import Citation, OfferAnalysis, OfferComponent
    from trajectory.storage import Storage

    user = build_test_user("uk_resident")
    storage = Storage()
    await storage.initialise()
    await storage.save_user_profile(user)

    last_session = build_test_session(user.user_id, intent="forward_job")
    await storage.save_session(last_session)

    fixture_citation = Citation(
        kind="url_snippet",
        url="acme-offer-letter.pdf",
        verbatim_snippet="Annual base salary: £82,000",
    )
    fixture_offer = OfferAnalysis(
        company_name="Acme Tech Ltd",
        role_title="Senior Software Engineer",
        base_salary_gbp=OfferComponent(
            label="base salary",
            value_text="£82,000",
            citation=fixture_citation,
        ),
        flags=[
            "Non-compete clause is 12 months — long for UK norms (3-6 typical).",
        ],
        market_comparison_note=(
            "£82k clears SOC 2136 going rate (£40,300) comfortably."
        ),
    )

    captured: dict = {}

    async def _fake_handle_analyse_offer(*, user, storage, session, text_pasted=None, pdf_bytes=None):
        captured["user_id"] = user.user_id
        captured["session_id"] = session.session_id if session else None
        captured["text_pasted"] = text_pasted
        captured["pdf_bytes_len"] = len(pdf_bytes) if pdf_bytes else 0
        return fixture_offer

    original = bot_handlers.handle_analyse_offer
    bot_handlers.handle_analyse_offer = _fake_handle_analyse_offer

    pasted_text = (
        "Dear Kene,\n\n"
        "We're delighted to offer you the role of Senior Software Engineer "
        "at Acme Tech Ltd. Annual base salary: £82,000. Standard 25 days "
        "annual leave plus public holidays. Notice period: 3 months either "
        "side after probation. Non-compete: 12 months post-termination "
        "within Greater London. We require you to confirm acceptance "
        "within 7 days of this letter.\n\n"
        "Best regards,\nAcme Tech HR"
    )
    update = _make_update(
        user_id=user.user_id, chat_id=999_900_011, text=pasted_text,
    )
    ctx = _make_context(storage)

    try:
        try:
            await bot_handlers._handle_analyse_offer_text(
                update, ctx, user, storage, pasted_text, last_session,
            )
        except Exception as exc:
            failures.append(
                f"_handle_analyse_offer_text raised: {exc!r}"
            )
            return messages, failures, ESTIMATED_COST_USD

        # ── Assertions ───────────────────────────────────────────────
        if update.message.reply_text.await_count != 1:
            failures.append(
                f"reply_text awaited {update.message.reply_text.await_count} "
                "time(s); expected 1 (the 'Analysing…' placeholder)."
            )
        else:
            placeholder = update.message.reply_text.await_args.args[0]
            if "Analysing" not in placeholder:
                failures.append(
                    f"placeholder reply unexpected: {placeholder!r}"
                )
            else:
                messages.append("'Analysing…' placeholder fired")

        if captured.get("text_pasted") != pasted_text:
            failures.append(
                "handle_analyse_offer was not invoked with the pasted "
                f"text — captured={captured.get('text_pasted')!r:.80}"
            )
        if captured.get("pdf_bytes_len", 0) != 0:
            failures.append(
                "handle_analyse_offer received pdf_bytes on the text "
                "path — wiring is wrong."
            )
        if captured.get("user_id") != user.user_id:
            failures.append("handle_analyse_offer got wrong user_id")
        if captured.get("session_id") != last_session.session_id:
            failures.append("handle_analyse_offer got wrong session_id")

        if update.message.reply_markdown.await_count != 1:
            failures.append(
                f"reply_markdown awaited "
                f"{update.message.reply_markdown.await_count} time(s); "
                "expected 1."
            )
        else:
            md = update.message.reply_markdown.await_args.args[0]
            if "Acme Tech Ltd" not in md:
                failures.append(
                    f"formatted analysis missing company name: {md!r}"
                )
            elif "Non-compete" not in md and "non-compete" not in md.lower():
                failures.append(
                    f"formatted analysis missing flag detail: {md!r}"
                )
            else:
                messages.append(
                    f"reply_markdown delivered formatted analysis "
                    f"({len(md)} chars)"
                )
    finally:
        bot_handlers.handle_analyse_offer = original
        await storage.close()

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
