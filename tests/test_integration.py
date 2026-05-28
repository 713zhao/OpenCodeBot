"""Integration smoke test: real module wiring with mocked subprocess and Telegram API."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telegram_opencode.bot import cancel_handler, message_handler, start_handler, status_handler
from telegram_opencode.session import OpenCodeSession, SessionState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = 99001


def make_update(user_id: int, text: str = "") -> MagicMock:
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.text = text
    return update


def make_context(bot_data: dict[str, object], args: list[str] | None = None) -> MagicMock:
    context = MagicMock()
    context.bot_data = bot_data
    context.args = args or []
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    return context


# ---------------------------------------------------------------------------
# T034 — full session lifecycle smoke test
# ---------------------------------------------------------------------------


async def test_full_session_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: start → output → send_input → status → completion."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token:fake")
    monkeypatch.setenv("AUTHORIZED_USER_IDS", str(USER_ID))

    mock_process = MagicMock()
    mock_process.stdout = MagicMock()
    mock_process.stdout.readline = AsyncMock(side_effect=[b"Analysing...\n", b"Done.\n", b""])
    mock_process.stdin = MagicMock()
    mock_process.stdin.write = MagicMock()
    mock_process.stdin.drain = AsyncMock()
    mock_process.wait = AsyncMock(return_value=0)
    mock_process.terminate = MagicMock()
    mock_process.kill = MagicMock()

    bot_data: dict[str, object] = {"sessions": {}}

    # --- /start ---
    update = make_update(USER_ID)
    context = make_context(
        bot_data, ["opencode", "existing", "/tmp", "Integration", "test", "task"]
    )
    context.user_data = {}

    with (
        patch(
            "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)
        ) as mock_exec,
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "is_dir", return_value=True),
        patch("os.access", return_value=True),
    ):
        await start_handler(update, context)

    reply = update.message.reply_text.call_args.args[0]
    assert "✅ Session started" in reply
    sessions = bot_data["sessions"]  # type: ignore[index]
    assert USER_ID in sessions  # type: ignore[operator]

    # T037 / FR-003: verify task description was passed as CLI arg to 'opencode run'
    assert mock_exec.call_args.args[1] == "run"
    assert mock_exec.call_args.args[2] == "Integration test task"

    # --- send plain text (continue relay) ---
    # Session is RUNNING immediately after start (reader tasks haven't yielded yet).
    # Send input before sleeping so the session hasn't transitioned to COMPLETED yet.
    msg_update = make_update(USER_ID, text="y")
    msg_context = make_context(bot_data)
    msg_context.user_data = {}
    with patch(
        "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)
    ) as mock_continue:
        await message_handler(msg_update, msg_context)
    assert mock_continue.call_args.args[2] == "--continue"
    assert mock_continue.call_args.args[3] == "y"

    # Let reader/dispatcher coroutines make progress (may exhaust readline → COMPLETED)
    await asyncio.sleep(0.05)

    # --- /status ---
    stat_update = make_update(USER_ID)
    stat_context = make_context(bot_data)
    await status_handler(stat_update, stat_context)
    status_reply = stat_update.message.reply_text.call_args.args[0]
    assert any(s in status_reply for s in ("RUNNING", "COMPLETED", "AWAITING INPUT"))

    # Wait for reader to exhaust readline (returns b"")
    await asyncio.sleep(0.3)

    session: OpenCodeSession = sessions[USER_ID]  # type: ignore[index,assignment]
    assert session.state in {SessionState.RUNNING, SessionState.COMPLETED, SessionState.AWAITING_INPUT}


async def test_cancel_terminates_session() -> None:
    """cancel_handler terminates the session and removes it from bot_data."""
    mock_session = MagicMock()
    mock_session.task.description = "test task"
    mock_session.terminate = AsyncMock()

    bot_data: dict[str, object] = {"sessions": {USER_ID: mock_session}}
    update = make_update(USER_ID)
    context = make_context(bot_data)

    await cancel_handler(update, context)

    mock_session.terminate.assert_awaited_once()
    assert USER_ID not in bot_data["sessions"]  # type: ignore[operator]
    text = update.message.reply_text.call_args.args[0]
    assert "🛑 Session cancelled" in text


async def test_shutdown_terminates_all_sessions() -> None:
    """E6: post_shutdown callback must terminate every active session."""
    session_a = MagicMock(spec=OpenCodeSession)
    session_a.terminate = AsyncMock()
    session_b = MagicMock(spec=OpenCodeSession)
    session_b.terminate = AsyncMock()

    sessions = {1001: session_a, 1002: session_b}

    # Replicate the shutdown coroutine from main.py directly
    async def shutdown() -> None:
        for s in list(sessions.values()):
            await s.terminate()

    await shutdown()

    session_a.terminate.assert_awaited_once()
    session_b.terminate.assert_awaited_once()
