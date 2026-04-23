"""Smoke test — Telegram bot boot path.

Confirms the bot wiring without actually polling Telegram for messages:

  - bot/app.py constructs the python-telegram-bot Application
  - `_post_init` runs, wires Storage into bot_data, sets bot commands
  - `bot.get_me()` round-trips against the Telegram REST API (proves
    the token works and we can reach api.telegram.org)
  - `on_start` runs against a synthetic Update for a brand-new user and
    enqueues an onboarding message
  - `on_message` runs against a synthetic message, routes through the
    intent router, and replies (or asks the user to /start first)

Cost: ~$0.05 (one intent_router call). Plus a free Telegram getMe ping.

What this does NOT do:
  - Doesn't run forward_job (that's covered by `verdict` and `phase4_cv`)
  - Doesn't post to your real Telegram chat (replies are captured by an
    in-memory mock)
  - Doesn't start the long-polling loop
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from ._common import (
    SmokeResult,
    prepare_environment,
    require_anthropic_key,
    require_env,
    run_smoke,
)

NAME = "bot_boot"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.05


def _make_update(*, user_id: int, chat_id: int, text: str):
    """Build a minimal Update that satisfies the handler code paths.

    python-telegram-bot's Update is a typed dataclass; we mock the bits
    the handlers actually touch (effective_user.id, effective_chat.id,
    message.text, reply_text, reply_html). Anything else stays None and
    the handlers don't read it.
    """
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.reply_html = AsyncMock()
    return update


def _make_context(storage):
    ctx = MagicMock()
    ctx.bot_data = {"storage": storage}
    ctx.bot.send_message = AsyncMock()
    ctx.bot.send_document = AsyncMock()
    ctx.bot.edit_message_text = AsyncMock()
    return ctx


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    # Token guard first — bot won't even construct without it.
    token_missing = require_env("TELEGRAM_BOT_TOKEN")
    if token_missing:
        return [], [token_missing], 0.0

    key_missing = require_anthropic_key()
    if key_missing:
        return [], [key_missing], 0.0

    from trajectory.bot.app import _post_init
    from trajectory.bot.handlers import on_start, on_message
    from trajectory.config import settings
    from telegram.ext import ApplicationBuilder

    messages: list[str] = []
    failures: list[str] = []

    # ── 1. Build the Application without starting polling ─────────────
    try:
        app = (
            ApplicationBuilder()
            .token(settings.telegram_bot_token)
            .post_init(_post_init)
            .build()
        )
    except Exception as exc:
        failures.append(f"ApplicationBuilder().build() raised: {exc!r}")
        return messages, failures, 0.0

    from ._common import build_test_user
    from trajectory.bot import handlers as bot_handlers

    user_id = "smoke_bot_user"
    chat_id = 999_900_001

    # Everything that touches `app.bot_data` MUST happen inside
    # `async with app:` — once the context exits, python-telegram-bot
    # tears down the application state. Clear the in-memory onboarding
    # session map first so a re-run from a stale state doesn't
    # contaminate this slice.
    bot_handlers._onboarding_sessions.pop(chat_id, None)

    try:
        async with app:
            # ── 2. Token validation via Telegram getMe ──────────────────
            try:
                me = await app.bot.get_me()
                messages.append(
                    f"bot identity: @{me.username} (id={me.id}, name={me.first_name!r})"
                )
            except Exception as exc:
                failures.append(f"bot.get_me() failed (token / network): {exc!r}")
                return messages, failures, 0.0

            # ── 3. Run _post_init manually ─────────────────────────────
            # python-telegram-bot v21 only fires post_init from
            # run_polling() / run_webhook() — not from `async with app:`.
            # We invoke it directly so the smoke test exercises the
            # same wiring the real bot startup would.
            await _post_init(app)
            storage = app.bot_data.get("storage")
            if storage is None:
                failures.append("_post_init did not wire 'storage' into bot_data")
                return messages, failures, 0.0
            messages.append("_post_init wired Storage into bot_data")

            # ── 4. /start for a new user — expect onboarding kicked off ─
            update = _make_update(user_id=42, chat_id=chat_id, text="/start")
            update.effective_user.id = user_id
            ctx = _make_context(storage)
            try:
                await on_start(update, ctx)
            except Exception as exc:
                failures.append(f"on_start raised: {exc!r}")
                return messages, failures, 0.0

            if update.message.reply_text.await_count == 0:
                failures.append(
                    "on_start did not call reply_text — onboarding never started"
                )
            else:
                first_arg = update.message.reply_text.await_args.args[0]
                snippet = first_arg.split("\n")[0][:60]
                messages.append(f"on_start replied: {snippet!r}")

            # ── 5. on_message routes "hi" through intent_router ────────
            user = build_test_user("uk_resident")
            user.user_id = user_id
            await storage.save_user_profile(user)

            # Clear the onboarding state planted by on_start above so the
            # gate lets the message through to intent routing.
            bot_handlers._onboarding_sessions.pop(chat_id, None)

            update2 = _make_update(user_id=42, chat_id=chat_id, text="hi")
            update2.effective_user.id = user_id
            ctx2 = _make_context(storage)
            try:
                await on_message(update2, ctx2)
            except Exception as exc:
                failures.append(f"on_message raised: {exc!r}")
                return messages, failures, ESTIMATED_COST_USD

            total_replies = (
                update2.message.reply_text.await_count
                + update2.message.reply_html.await_count
                + ctx2.bot.send_message.await_count
            )
            if total_replies == 0:
                failures.append(
                    "on_message handled chitchat but produced no reply — silent drop"
                )
            else:
                messages.append(
                    f"on_message produced {total_replies} reply(ies) for 'hi'"
                )
    finally:
        # Ensure the in-process onboarding state doesn't leak across
        # smoke runs.
        bot_handlers._onboarding_sessions.pop(chat_id, None)

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
