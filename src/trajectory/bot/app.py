"""Telegram bot entry point.

Long-polling, single-user demo.
Run: python -m trajectory.bot.app
"""

from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from ..config import settings
from ..storage import Storage
from .handlers import on_message, on_start

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


async def _post_init(app) -> None:
    """Wire storage into bot_data and set bot commands."""
    storage = Storage()
    await storage.initialise()
    app.bot_data["storage"] = storage

    await app.bot.set_my_commands(
        [
            BotCommand("start", "Set up your profile"),
            BotCommand("help", "Show what I can do"),
        ]
    )
    log.info("Bot initialised. Storage ready.")


async def _post_shutdown(app) -> None:
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    log.info("Starting Trajectory bot (long-polling)…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
