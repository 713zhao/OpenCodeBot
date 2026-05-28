"""Tests for telegram_opencode.bot module."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telegram_opencode.bot import (
    cancel_handler,
    help_handler,
    message_handler,
    require_auth,
    start_handler,
    status_handler,
)
from telegram_opencode.config import Config
from telegram_opencode.session import OpenCodeSession, SessionState, SessionStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

USER_ID = 12345


@pytest.fixture()
def authorized_config() -> Config:
    return Config(bot_token="test", authorized_user_ids=frozenset({USER_ID}))


@pytest.fixture()
def mock_update() -> MagicMock:
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = USER_ID
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.text = "some text"
    return update


@pytest.fixture()
def mock_context() -> MagicMock:
    context = MagicMock()
    context.args = []
    context.bot_data = {"sessions": {}}
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    return context


# ---------------------------------------------------------------------------
# T020 — require_auth decorator
# ---------------------------------------------------------------------------


async def test_authorized_passes(mock_update: MagicMock, mock_context: MagicMock) -> None:
    config = Config(bot_token="t", authorized_user_ids=frozenset({USER_ID}))
    handler = AsyncMock()
    wrapped = require_auth(config)(handler)
    await wrapped(mock_update, mock_context)
    handler.assert_awaited_once()


async def test_unauthorized_silently_rejected(
    mock_update: MagicMock, mock_context: MagicMock
) -> None:
    config = Config(bot_token="t", authorized_user_ids=frozenset({99999}))
    handler = AsyncMock()
    wrapped = require_auth(config)(handler)
    await wrapped(mock_update, mock_context)
    handler.assert_not_awaited()
    mock_update.message.reply_text.assert_not_called()


async def test_none_user_rejected(mock_update: MagicMock, mock_context: MagicMock) -> None:
    mock_update.effective_user = None
    config = Config(bot_token="t", authorized_user_ids=frozenset({USER_ID}))
    handler = AsyncMock()
    wrapped = require_auth(config)(handler)
    await wrapped(mock_update, mock_context)
    handler.assert_not_awaited()


async def test_wraps_preserves_name(mock_update: MagicMock, mock_context: MagicMock) -> None:
    config = Config(bot_token="t", authorized_user_ids=frozenset({USER_ID}))

    async def my_handler(update: MagicMock, context: MagicMock) -> None:
        pass

    wrapped = require_auth(config)(my_handler)  # type: ignore[arg-type]
    assert wrapped.__name__ == "my_handler"


# ---------------------------------------------------------------------------
# T021 — help_handler
# ---------------------------------------------------------------------------


async def test_help_handler(mock_update: MagicMock, mock_context: MagicMock) -> None:
    await help_handler(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    text = mock_update.message.reply_text.call_args.args[0]
    assert "/start" in text
    assert "/status" in text
    assert "/cancel" in text
    assert "/help" in text


# ---------------------------------------------------------------------------
# T022 — start_handler error paths
# ---------------------------------------------------------------------------


async def test_start_no_args(mock_update: MagicMock, mock_context: MagicMock) -> None:
    mock_context.args = []
    await start_handler(mock_update, mock_context)
    text = mock_update.message.reply_text.call_args.args[0]
    assert "Usage:" in text


async def test_start_invalid_task_type(mock_update: MagicMock, mock_context: MagicMock) -> None:
    mock_context.args = ["foo", "/tmp", "desc"]
    await start_handler(mock_update, mock_context)
    text = mock_update.message.reply_text.call_args.args[0]
    assert "Invalid task type" in text


async def test_start_directory_not_found(mock_update: MagicMock, mock_context: MagicMock) -> None:
    mock_context.args = ["existing", "/nonexistent/path", "desc"]
    with patch.object(Path, "exists", return_value=False):
        await start_handler(mock_update, mock_context)
    text = mock_update.message.reply_text.call_args.args[0]
    assert "⚠️ Directory not found" in text


async def test_start_path_not_a_directory(mock_update: MagicMock, mock_context: MagicMock) -> None:
    mock_context.args = ["existing", "/tmp/somefile", "desc"]
    with (
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "is_dir", return_value=False),
    ):
        await start_handler(mock_update, mock_context)
    text = mock_update.message.reply_text.call_args.args[0]
    assert "❌ Path is not a directory" in text


async def test_start_session_already_running(
    mock_update: MagicMock, mock_context: MagicMock
) -> None:
    mock_context.args = ["existing", "/tmp", "desc"]
    mock_context.bot_data["sessions"][USER_ID] = MagicMock()
    with (
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "is_dir", return_value=True),
        patch("os.access", return_value=True),
    ):
        await start_handler(mock_update, mock_context)
    text = mock_update.message.reply_text.call_args.args[0]
    assert "⚠️ A session is already running" in text


# ---------------------------------------------------------------------------
# T023 — start_handler success path
# ---------------------------------------------------------------------------


async def test_start_handler_success(mock_update: MagicMock, mock_context: MagicMock) -> None:
    mock_context.args = ["existing", "/home/dev/proj", "Fix", "the", "bug"]

    with (
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "is_dir", return_value=True),
        patch("os.access", return_value=True),
        patch.object(OpenCodeSession, "start", new_callable=AsyncMock),
    ):
        await start_handler(mock_update, mock_context)

    assert USER_ID in mock_context.bot_data["sessions"]
    text = mock_update.message.reply_text.call_args.args[0]
    assert "✅ Session started" in text
    assert "Fix the bug" in text


# ---------------------------------------------------------------------------
# T024 — status_handler
# ---------------------------------------------------------------------------


async def test_status_handler_running(mock_update: MagicMock, mock_context: MagicMock) -> None:
    mock_session = MagicMock()
    mock_session.get_status.return_value = SessionStatus(
        state=SessionState.RUNNING,
        task_description="mytask",
        task_type="existing",
        working_directory="/proj",
        recent_output=["line1"],
        started_at=datetime.now(UTC),
    )
    mock_context.bot_data["sessions"][USER_ID] = mock_session

    await status_handler(mock_update, mock_context)

    text = mock_update.message.reply_text.call_args.args[0]
    assert "RUNNING" in text
    assert "mytask" in text
    assert "/proj" in text
    assert "line1" in text


async def test_status_handler_awaiting_input(
    mock_update: MagicMock, mock_context: MagicMock
) -> None:
    mock_session = MagicMock()
    mock_session.get_status.return_value = SessionStatus(
        state=SessionState.AWAITING_INPUT,
        task_description="mytask",
        task_type="existing",
        working_directory="/proj",
        recent_output=[],
        started_at=datetime.now(UTC),
    )
    mock_context.bot_data["sessions"][USER_ID] = mock_session

    await status_handler(mock_update, mock_context)

    text = mock_update.message.reply_text.call_args.args[0]
    assert "AWAITING INPUT" in text


async def test_status_handler_no_session(mock_update: MagicMock, mock_context: MagicMock) -> None:
    await status_handler(mock_update, mock_context)
    text = mock_update.message.reply_text.call_args.args[0]
    assert "💤 No active session" in text


# ---------------------------------------------------------------------------
# T025 — cancel_handler
# ---------------------------------------------------------------------------


async def test_cancel_active_session(mock_update: MagicMock, mock_context: MagicMock) -> None:
    mock_session = MagicMock()
    mock_session.task.description = "my task"
    mock_session.terminate = AsyncMock()
    mock_context.bot_data["sessions"][USER_ID] = mock_session

    await cancel_handler(mock_update, mock_context)

    mock_session.terminate.assert_awaited_once()
    assert USER_ID not in mock_context.bot_data["sessions"]
    text = mock_update.message.reply_text.call_args.args[0]
    assert "🛑 Session cancelled" in text
    assert "my task" in text


async def test_cancel_no_session(mock_update: MagicMock, mock_context: MagicMock) -> None:
    await cancel_handler(mock_update, mock_context)
    text = mock_update.message.reply_text.call_args.args[0]
    assert "ℹ️ No active session" in text


# ---------------------------------------------------------------------------
# T026 — message_handler
# ---------------------------------------------------------------------------


async def test_message_handler_running(mock_update: MagicMock, mock_context: MagicMock) -> None:
    mock_context.user_data = {}
    mock_update.message.text = "hello"
    mock_session = MagicMock()
    mock_session.state = SessionState.RUNNING
    mock_session.send_input = AsyncMock()
    mock_context.bot_data["sessions"][USER_ID] = mock_session

    await message_handler(mock_update, mock_context)

    mock_session.send_input.assert_awaited_once_with("hello")
    mock_update.message.reply_text.assert_called_once_with("⏳ Processing your input...")


async def test_message_handler_awaiting_input(
    mock_update: MagicMock, mock_context: MagicMock
) -> None:
    mock_context.user_data = {}
    mock_update.message.text = "y"
    mock_session = MagicMock()
    mock_session.state = SessionState.AWAITING_INPUT
    mock_session.send_input = AsyncMock()
    mock_context.bot_data["sessions"][USER_ID] = mock_session

    await message_handler(mock_update, mock_context)

    mock_session.send_input.assert_awaited_once_with("y")


async def test_message_handler_no_session(mock_update: MagicMock, mock_context: MagicMock) -> None:
    mock_context.user_data = {}  # Ensure pending_mkdir is not matched accidentally
    await message_handler(mock_update, mock_context)
    text = mock_update.message.reply_text.call_args.args[0]
    assert "No active session" in text


async def test_message_handler_completed_session(
    mock_update: MagicMock, mock_context: MagicMock
) -> None:
    mock_context.user_data = {}
    mock_session = MagicMock()
    mock_session.state = SessionState.COMPLETED
    mock_context.bot_data["sessions"][USER_ID] = mock_session

    await message_handler(mock_update, mock_context)

    text = mock_update.message.reply_text.call_args.args[0]
    assert "Session has ended" in text


async def test_message_handler_failed_session(
    mock_update: MagicMock, mock_context: MagicMock
) -> None:
    mock_context.user_data = {}
    mock_session = MagicMock()
    mock_session.state = SessionState.FAILED
    mock_context.bot_data["sessions"][USER_ID] = mock_session

    await message_handler(mock_update, mock_context)

    text = mock_update.message.reply_text.call_args.args[0]
    assert "Session has ended" in text
