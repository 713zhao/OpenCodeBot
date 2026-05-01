"""Entry point: wire the PTB Application and start polling."""

import logging
from typing import Any

from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, filters

from .bot import (
    cancel_handler,
    help_handler,
    message_handler,
    require_auth,
    start_handler,
    status_handler,
)
from .config import load_config
from .session import OpenCodeSession

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Configure and run the Telegram OpenCode bridge bot."""
    config = load_config()
    logger.info("Starting Telegram OpenCode Bridge Bot...")
    logger.info("Authorized users: %d configured", len(config.authorized_user_ids))

    async def shutdown(app: Application[Any, Any, Any, Any, Any, Any]) -> None:
        sessions: dict[int, OpenCodeSession] = app.bot_data.get("sessions", {})
        for session in list(sessions.values()):
            await session.terminate()

    application: Application[Any, Any, Any, Any, Any, Any] = (
        ApplicationBuilder().token(config.bot_token).post_shutdown(shutdown).build()
    )
    application.bot_data["sessions"] = {}

    auth = require_auth(config)

    application.add_handler(CommandHandler("start", auth(start_handler)))
    application.add_handler(CommandHandler("status", auth(status_handler)))
    application.add_handler(CommandHandler("cancel", auth(cancel_handler)))
    application.add_handler(CommandHandler("help", auth(help_handler)))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, auth(message_handler))
    )

    logger.info("Bot polling started.")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
