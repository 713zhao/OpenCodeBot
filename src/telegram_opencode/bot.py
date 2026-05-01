"""Telegram bot command/message handlers and authorization decorator."""

import functools
import logging
import os
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from .config import Config
from .session import OpenCodeSession, SessionState, Task

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type alias for PTB handler functions
# ---------------------------------------------------------------------------

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]


# ---------------------------------------------------------------------------
# Authorization decorator
# ---------------------------------------------------------------------------


def require_auth(config: Config) -> Callable[[Handler], Handler]:
    """Return a decorator that enforces user-ID-based authorization."""

    def decorator(handler: Handler) -> Handler:
        @functools.wraps(handler)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            user_id = update.effective_user.id if update.effective_user else None
            if user_id not in config.authorized_user_ids:
                logger.warning("Unauthorized access attempt from user_id=%s", user_id)
                return
            await handler(update, context)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the command listing help message."""
    text = (
        "🤖 OpenCode Bridge Bot\n\n"
        "Commands:\n"
        "  /start [existing|new] <path> <description> — Start a coding session\n"
        "  /status — Show current session status\n"
        "  /cancel — Cancel the running session\n"
        "  /help — Show this message"
    )
    await update.message.reply_text(text)  # type: ignore[union-attr]


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parse args, validate path, create Task, start OpenCodeSession."""
    if update.effective_user is None or update.message is None:
        return
    args: list[str] = list(context.args or [])
    user_id: int = update.effective_user.id
    message = update.message

    if len(args) < 3:
        await message.reply_text("Usage: /start [existing|new] <path> <description>")
        return

    task_type = args[0]
    if task_type not in ("existing", "new"):
        await message.reply_text("Invalid task type. Use 'existing' or 'new'.")
        return

    path = Path(args[1]).expanduser().resolve()

    if not path.exists():
        context.user_data["pending_mkdir"] = {
            "path": str(path),
            "task_type": task_type,
            "description": " ".join(args[2:]),
        }
        await message.reply_text(
            f"⚠️ Directory not found: {path}\n"
            "Would you like to create it? Reply *yes* or *no*.",
            parse_mode="Markdown",
        )
        return

    if not path.is_dir():
        await message.reply_text(f"❌ Path is not a directory: {path}")
        return

    if not os.access(path, os.R_OK):
        await message.reply_text(f"❌ Directory is not accessible: {path}")
        return

    sessions: dict[int, OpenCodeSession] = context.bot_data.setdefault("sessions", {})
    if sessions.get(user_id) is not None:
        await message.reply_text(
            "⚠️ A session is already running. "
            "Send /cancel to stop it first, or wait for it to complete."
        )
        return

    description = " ".join(args[2:])
    task = Task(
        description=description,
        task_type=task_type,  # type: ignore[arg-type]
        working_directory=path,
    )

    bot = context.bot

    async def send_callback(text: str) -> None:
        await bot.send_message(chat_id=user_id, text=text)

    session = OpenCodeSession(task, send_callback)
    try:
        await session.start()
    except FileNotFoundError:
        await message.reply_text(
            "❌ Could not start session: the `opencode` CLI was not found.\n"
            "Please ensure OpenCode is installed and available on PATH."
        )
        return
    except Exception as exc:
        logger.error("Failed to start session for user_id=%s: %s", user_id, exc, exc_info=True)
        await message.reply_text(f"❌ Failed to start session: {exc}")
        return
    sessions[user_id] = session
    logger.info("Session started for user_id=%s type=%s dir=%s", user_id, task_type, path)

    type_label = "Existing project" if task_type == "existing" else "New project"
    await message.reply_text(
        f"✅ Session started\n"
        f"Task: {description}\n"
        f"Type: {type_label}\n"
        f"Directory: {path}"
    )


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Report the current session state and recent output."""
    if update.effective_user is None or update.message is None:
        return
    user_id: int = update.effective_user.id
    message = update.message
    sessions: dict[int, OpenCodeSession] = context.bot_data.get("sessions", {})
    session = sessions.get(user_id)

    if session is None:
        await message.reply_text("💤 No active session. Use /start to begin a task.")
        return

    status = session.get_status()
    state_name = status.state.name.replace("_", " ")
    started_str = (
        status.started_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        if status.started_at
        else "unknown"
    )
    recent = "\n".join(f"> {line.rstrip()}" for line in status.recent_output)
    type_label = "Existing project" if status.task_type == "existing" else "New project"

    text = (
        f"📊 Session Status\n\n"
        f"State: {state_name}\n"
        f"Task: {status.task_description}\n"
        f"Type: {type_label}\n"
        f"Directory: {status.working_directory}\n"
        f"Started: {started_str}\n\n"
        f"Recent output:\n{recent}"
    )
    await message.reply_text(text)


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Terminate the active session and remove it from bot_data."""
    if update.effective_user is None or update.message is None:
        return
    user_id: int = update.effective_user.id
    message = update.message
    sessions: dict[int, OpenCodeSession] = context.bot_data.get("sessions", {})
    session = sessions.get(user_id)

    if session is None:
        await message.reply_text("ℹ️ No active session to cancel.")
        return

    task_description = session.task.description
    await session.terminate()
    del sessions[user_id]
    logger.info("Session cancelled by user_id=%s", user_id)

    await message.reply_text(
        f"🛑 Session cancelled.\n"
        f"Task: {task_description}\n"
        f"Exit: terminated by user"
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Relay plain-text messages as stdin to the active session."""
    if update.effective_user is None or update.message is None or update.message.text is None:
        return
    user_id: int = update.effective_user.id
    message = update.message

    # Handle pending directory-creation confirmation
    pending = (context.user_data or {}).get("pending_mkdir")
    if pending is not None:
        reply = (message.text or "").strip().lower()
        if reply in ("yes", "y"):
            mkdir_path = Path(pending["path"])
            try:
                mkdir_path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                context.user_data.pop("pending_mkdir", None)
                await message.reply_text(f"❌ Failed to create directory: {exc}")
                return
            context.user_data.pop("pending_mkdir", None)
            pending_sessions: dict[int, OpenCodeSession] = context.bot_data.setdefault("sessions", {})
            if pending_sessions.get(user_id) is not None:
                await message.reply_text("⚠️ A session is already running. Send /cancel to stop it first.")
                return
            task_type = pending["task_type"]
            description = pending["description"]
            task = Task(
                description=description,
                task_type=task_type,  # type: ignore[arg-type]
                working_directory=mkdir_path,
            )
            bot = context.bot

            async def _mkdir_send_callback(text: str) -> None:
                await bot.send_message(chat_id=user_id, text=text)

            new_session = OpenCodeSession(task, _mkdir_send_callback)
            try:
                await new_session.start()
            except FileNotFoundError:
                await message.reply_text(
                    "❌ Could not start session: the `opencode` CLI was not found.\n"
                    "Please ensure OpenCode is installed and available on PATH."
                )
                return
            except Exception as exc:
                logger.error("Failed to start session for user_id=%s: %s", user_id, exc, exc_info=True)
                await message.reply_text(f"❌ Failed to start session: {exc}")
                return
            pending_sessions[user_id] = new_session
            logger.info("Session started (after mkdir) for user_id=%s type=%s dir=%s", user_id, task_type, mkdir_path)
            type_label = "Existing project" if task_type == "existing" else "New project"
            await message.reply_text(
                f"✅ Directory created and session started\n"
                f"Task: {description}\n"
                f"Type: {type_label}\n"
                f"Directory: {mkdir_path}"
            )
        elif reply in ("no", "n"):
            context.user_data.pop("pending_mkdir", None)
            await message.reply_text("❌ Session creation cancelled.")
        else:
            await message.reply_text("Please reply with *yes* or *no*.", parse_mode="Markdown")
        return

    sessions: dict[int, OpenCodeSession] = context.bot_data.get("sessions", {})
    session = sessions.get(user_id)

    if session is None:
        await message.reply_text("ℹ️ No active session. Use /start to begin a task.")
        return

    if session.state in {SessionState.COMPLETED, SessionState.FAILED}:
        await message.reply_text("ℹ️ Session has ended. Use /start to begin a new task.")
        return

    if session.state in {SessionState.RUNNING, SessionState.AWAITING_INPUT}:
        await session.send_input(message.text or "")
