"""Telegram bot entry point.

Long-polling, single-user demo.
Run: python -m askpicky.bot.app
"""

from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from ..config import settings
from ..notifications.scheduler import start_scheduler, stop_scheduler
from ..observability import install_correlation_filter
from ..storage import Storage
from .handlers import on_message, on_outcome_callback, on_start

# Only configure logging if this is the entrypoint. In Docker / cloud,
# the process runner (uvicorn, systemd) owns logging configuration.
import sys as _sys
if _sys.argv and _sys.argv[0].endswith(("bot.py", "bot", "run_bot")):
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s req=%(request_id)s ses=%(session_id)s — %(message)s",
        level=logging.INFO,
    )
install_correlation_filter()
log = logging.getLogger(__name__)


async def _post_init(app) -> None:
    """Wire storage into bot_data, set bot commands, start the
    notifications scheduler."""
    storage = Storage()
    await storage.initialise()
    app.bot_data["storage"] = storage

    await app.bot.set_my_commands(
        [
            BotCommand("start", "Set up your profile"),
            BotCommand("help", "Show what I can do"),
        ]
    )
    await start_scheduler(storage)
    log.info("Bot initialised. Storage ready. Nudge scheduler running.")


async def _post_shutdown(app) -> None:
    await stop_scheduler()
    storage: Storage = app.bot_data.get("storage")
    if storage:
        await storage.close()
    log.info("Bot shutdown complete.")


def main() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in environment")

    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("help", on_start))
    app.add_handler(
        CallbackQueryHandler(on_outcome_callback, pattern=r"^ask:outcome:"),
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    log.info("Starting AskPicky bot (long-polling)…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
