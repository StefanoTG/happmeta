"""
Telegram bot entrypoint. Run with:

    python -m bot.bot
"""
from __future__ import annotations

import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.config import get_config
from app.database import get_db
from app.logger import setup_logger

from .handlers import cmd_start, on_callback, on_message


def build_app() -> Application:
    cfg = get_config()
    setup_logger("subproxy.bot",
                 log_file=cfg.paths.get("log_file"),
                 level=cfg.middleware.get("log_level", "INFO"))
    get_db()  # ensure schema exists

    token = cfg.telegram.get("bot_token")
    if not token or token == "REPLACE_ME":
        raise RuntimeError("Telegram bot_token is not configured.")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    return app


def main() -> None:
    app = build_app()
    logging.getLogger("subproxy.bot").info("Starting Telegram bot (polling)…")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
