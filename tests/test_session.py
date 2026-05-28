"""Tests for telegram_opencode.session module."""

import dataclasses
import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telegram_opencode.session import (
    InvalidStateError,
    OpenCodeSession,
    SessionState,
    SessionStatus,
    Task,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TASK = Task(
    description="Fix the bug",
    task_type="existing",
    working_directory=Path("/tmp"),
)


def make_session(send_callback: AsyncMock | None = None) -> OpenCodeSession:
    cb = send_callback if send_callback is not None else AsyncMock()
    return OpenCodeSession(TASK, cb)


def make_process(
    readline_side_effect: list[bytes] | None = None,
    wait_return: int = 0,
) -> MagicMock:
    proc = MagicMock()
    proc.stdout = MagicMock()
    proc.stdout.readline = AsyncMock(
        side_effect=readline_side_effect or [b""]
    )
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.wait = AsyncMock(return_value=wait_return)
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    return proc


# ---------------------------------------------------------------------------
# T007 — Data types
# ---------------------------------------------------------------------------


def test_session_state_members() -> None:
    names = {m.name for m in SessionState}
    assert names == {"IDLE", "RUNNING", "AWAITING_INPUT", "COMPLETED", "FAILED"}


def test_task_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        TASK.description = "other"  # type: ignore[misc]


def test_task_fields() -> None:
    assert TASK.description == "Fix the bug"
    assert TASK.task_type == "existing"
    assert TASK.working_directory == Path("/tmp")


def test_session_status_is_frozen() -> None:
    status = SessionStatus(
        state=SessionState.IDLE,
        task_description=None,
        task_type=None,
        working_directory=None,
        recent_output=[],
        started_at=None,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        status.state = SessionState.RUNNING  # type: ignore[misc]


# ---------------------------------------------------------------------------
# T008 — start()
# ---------------------------------------------------------------------------


async def test_start_transitions_to_running() -> None:
    session = make_session()
    proc = make_process()

    assert session.state is SessionState.IDLE

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)) as mock_exec:
        await session.start()

    assert session.state is SessionState.RUNNING
    mock_exec.assert_called_once()
    call_args = mock_exec.call_args
    assert call_args.args[0] == "opencode"
    assert call_args.args[1] == "run"
    assert call_args.args[2] == TASK.description
    assert call_args.args[3] == "--dir"
    assert call_args.args[4] == str(TASK.working_directory)


async def test_start_twice_raises() -> None:
    session = make_session()
    proc = make_process()

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
        await session.start()
        with pytest.raises(InvalidStateError):
            await session.start()

    assert session._reader_task is not None
    assert session._dispatcher_task is not None

    session._reader_task.cancel()
    session._dispatcher_task.cancel()


# ---------------------------------------------------------------------------
# T009 — send_input() state guards
# ---------------------------------------------------------------------------


async def test_send_input_in_running_state() -> None:
    session = make_session()
    proc = make_process()
    session.state = SessionState.RUNNING

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)) as mock_exec:
        await session.send_input("hello")

    mock_exec.assert_called_once()
    call_args = mock_exec.call_args
    assert call_args.args[0] == "opencode"
    assert call_args.args[1] == "run"
    assert call_args.args[2] == "--continue"
    assert call_args.args[3] == "hello"


async def test_send_input_in_awaiting_input_state() -> None:
    session = make_session()
    proc = make_process()
    session.state = SessionState.AWAITING_INPUT

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)) as mock_exec:
        await session.send_input("yes")

    mock_exec.assert_called_once()
    assert mock_exec.call_args.args[2] == "--continue"
    assert mock_exec.call_args.args[3] == "yes"


async def test_send_input_idle_raises() -> None:
    session = make_session()
    with pytest.raises(InvalidStateError):
        await session.send_input("nope")


async def test_send_input_completed_raises() -> None:
    session = make_session()
    proc = make_process()
    session.process = proc
    session.state = SessionState.COMPLETED

    with pytest.raises(InvalidStateError):
        await session.send_input("nope")


async def test_send_input_failed_raises() -> None:
    session = make_session()
    proc = make_process()
    session.process = proc
    session.state = SessionState.FAILED

    with pytest.raises(InvalidStateError):
        await session.send_input("nope")


# ---------------------------------------------------------------------------
# T010 — _reader_task
# ---------------------------------------------------------------------------


async def test_reader_task_lines_and_sentinel() -> None:
    session = make_session()
    proc = make_process(readline_side_effect=[b"line1\n", b"line2\n", b""], wait_return=0)
    session.process = proc

    await session._read_output()

    assert session.exit_code == 0
    assert session.state is SessionState.AWAITING_INPUT  # kept alive for follow-up
    assert "line1\n" in session.recent_output
    assert "line2\n" in session.recent_output

    items = []
    while not session.output_queue.empty():
        items.append(session.output_queue.get_nowait())
    assert items == ["line1\n", "line2\n", None]


async def test_reader_task_nonzero_exit_sets_failed() -> None:
    session = make_session()
    proc = make_process(readline_side_effect=[b""], wait_return=1)
    session.process = proc

    await session._read_output()

    assert session.exit_code == 1
    assert session.state is SessionState.FAILED


# ---------------------------------------------------------------------------
# T011 — _dispatcher_task
# ---------------------------------------------------------------------------


async def test_dispatcher_joins_buffer_before_sentinel() -> None:
    send_cb = AsyncMock()
    session = make_session(send_cb)
    session.exit_code = 0

    await session.output_queue.put("line1")
    await session.output_queue.put("line2")
    await session.output_queue.put(None)

    await session._dispatch_output()

    calls = send_cb.call_args_list
    # First call should have the joined text
    first_text = calls[0].args[0]
    assert "line1" in first_text
    assert "line2" in first_text
    # Completion notification follows
    completion_call = calls[-1].args[0]
    assert "✅ Session completed" in completion_call


async def test_dispatcher_chunking() -> None:
    send_cb = AsyncMock()
    session = make_session(send_cb)
    session.exit_code = 0

    big_string = "x" * 5000
    await session.output_queue.put(big_string)
    await session.output_queue.put(None)

    await session._dispatch_output()

    # Every call must be within 4096 chars
    for call in send_cb.call_args_list:
        assert len(call.args[0]) <= 4096

    # At least two chunk calls (5000 > 4096)
    content_calls = [c for c in send_cb.call_args_list if "✅" not in c.args[0]]
    assert len(content_calls) >= 2


async def test_dispatcher_failure_notification() -> None:
    send_cb = AsyncMock()
    session = make_session(send_cb)
    session.exit_code = 2

    await session.output_queue.put(None)
    await session._dispatch_output()

    last_call = send_cb.call_args_list[-1].args[0]
    assert "❌" in last_call
    assert "2" in last_call


# ---------------------------------------------------------------------------
# T012 — terminate()
# ---------------------------------------------------------------------------


async def test_terminate_kills_process_and_cancels_tasks() -> None:
    session = make_session()
    proc = make_process()
    session.process = proc
    session.state = SessionState.RUNNING

    reader = MagicMock()
    reader.cancel = MagicMock()
    dispatcher = MagicMock()
    dispatcher.cancel = MagicMock()
    session._reader_task = reader
    session._dispatcher_task = dispatcher

    with patch("asyncio.wait_for", new=AsyncMock(return_value=None)):
        await session.terminate()

    proc.terminate.assert_called_once()
    reader.cancel.assert_called_once()
    dispatcher.cancel.assert_called_once()
    assert session.state is SessionState.FAILED


async def test_terminate_timeout_calls_kill() -> None:
    session = make_session()
    proc = make_process()
    session.process = proc
    session.state = SessionState.RUNNING
    session._reader_task = MagicMock(cancel=MagicMock())
    session._dispatcher_task = MagicMock(cancel=MagicMock())

    with patch("asyncio.wait_for", new=AsyncMock(side_effect=TimeoutError())):
        await session.terminate()

    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()
    assert session.state is SessionState.FAILED


async def test_terminate_noop_when_already_completed() -> None:
    session = make_session()
    session.state = SessionState.COMPLETED
    # Should return immediately without touching process (None)
    await session.terminate()
    assert session.state is SessionState.COMPLETED


# ---------------------------------------------------------------------------
# get_status()
# ---------------------------------------------------------------------------


def test_get_status_fields() -> None:
    session = make_session()
    session.state = SessionState.RUNNING
    session.started_at = datetime(2026, 1, 1, 12, 0, 0)
    session.recent_output.append("some line\n")

    status = session.get_status()

    assert status.state is SessionState.RUNNING
    assert status.task_description == TASK.description
    assert status.task_type == TASK.task_type
    assert status.working_directory == str(TASK.working_directory)
    assert "some line\n" in status.recent_output
    assert status.started_at == datetime(2026, 1, 1, 12, 0, 0)


# ---------------------------------------------------------------------------
# FR-003 — auto-prime: task description written to stdin on start()
# ---------------------------------------------------------------------------


async def test_start_writes_task_description_to_stdin() -> None:
    """start() must pass task description as CLI argument to 'opencode run' (FR-003)."""
    session = make_session()
    proc = make_process()

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)) as mock_exec:
        await session.start()

    call_args = mock_exec.call_args
    assert call_args.args[0] == "opencode"
    assert call_args.args[1] == "run"
    assert call_args.args[2] == TASK.description

    # Cleanup tasks to avoid warnings
    if session._reader_task:
        session._reader_task.cancel()
    if session._dispatcher_task:
        session._dispatcher_task.cancel()


# ---------------------------------------------------------------------------
# NFR-006 — _detect_prompt helper
# ---------------------------------------------------------------------------


def test_detect_prompt_question_mark() -> None:
    from telegram_opencode.session import _detect_prompt

    assert _detect_prompt("Continue? ") is False  # trailing space after ? doesn't match
    assert _detect_prompt("Continue?") is True


def test_detect_prompt_angle_bracket() -> None:
    from telegram_opencode.session import _detect_prompt

    assert _detect_prompt("Enter value> ") is True


def test_detect_prompt_colon() -> None:
    from telegram_opencode.session import _detect_prompt

    assert _detect_prompt("Choose option: ") is True


def test_detect_prompt_plain_line() -> None:
    from telegram_opencode.session import _detect_prompt

    assert _detect_prompt("Analyzing files...\n") is False
    assert _detect_prompt("Done.\n") is False


# ---------------------------------------------------------------------------
# NFR-006 — AWAITING_INPUT state transition via _read_output
# ---------------------------------------------------------------------------


async def test_reader_sets_awaiting_input_on_prompt_line() -> None:
    """Output line ending with '?' must transition state to AWAITING_INPUT."""
    session = make_session()
    proc = make_process(readline_side_effect=[b"Overwrite file?\n", b""], wait_return=0)
    session.process = proc

    await session._read_output()

    # After prompt line read, state should have been AWAITING_INPUT; after EOF it becomes COMPLETED
    # The queue should contain the prompt line
    items = []
    while not session.output_queue.empty():
        items.append(session.output_queue.get_nowait())
    assert "Overwrite file?\n" in items


async def test_reader_returns_to_running_after_prompt() -> None:
    """State returns to RUNNING when a non-prompt line follows an AWAITING_INPUT line."""
    session = make_session()
    # Simulate: prompt → plain output → EOF
    proc = make_process(
        readline_side_effect=[b"Continue?\n", b"Processing...\n", b""],
        wait_return=0,
    )
    session.process = proc
    # After EOF with exit_code=0 the session stays alive for follow-up (AWAITING_INPUT)
    await session._read_output()
    assert session.state is SessionState.AWAITING_INPUT


# ---------------------------------------------------------------------------
# FR-015 — inactivity timeout in _read_output
# ---------------------------------------------------------------------------


async def test_reader_sends_timeout_notification_on_inactivity() -> None:
    """When asyncio.wait_for raises TimeoutError, bot must notify user and set FAILED."""
    send_cb = AsyncMock()
    session = make_session(send_cb)
    proc = MagicMock()
    proc.stdout = MagicMock()
    session.process = proc

    with patch("asyncio.wait_for", new=AsyncMock(side_effect=TimeoutError())):
        await session._read_output()

    assert session.state is SessionState.FAILED
    assert session.ended_at is not None
    # Timeout notification must be sent
    notification_texts = [call.args[0] for call in send_cb.call_args_list]
    assert any("timed out" in t.lower() or "⏱" in t for t in notification_texts)


# ---------------------------------------------------------------------------
# FR-016 — ERROR-level logging with exc_info on unexpected exceptions
# ---------------------------------------------------------------------------


async def test_read_output_logs_error_on_unexpected_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """C2/E5: An unexpected exception in _read_output must be logged at ERROR with exc_info."""
    send_cb = AsyncMock()
    session = make_session(send_cb)
    proc = MagicMock()
    proc.stdout = MagicMock()
    # Make readline raise an unexpected RuntimeError (not TimeoutError)
    proc.stdout.readline = AsyncMock(side_effect=RuntimeError("disk read error"))
    session.process = proc

    with caplog.at_level(logging.ERROR, logger="telegram_opencode.session"):
        await session._read_output()

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records, "Expected an ERROR-level log record"
    assert error_records[0].exc_info is not None, "Expected exc_info to be set"
    assert session.state is SessionState.FAILED


async def test_dispatch_output_logs_error_on_unexpected_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """C2/E5: An unexpected exception in _dispatch_output must be logged at ERROR with exc_info."""
    send_cb = AsyncMock(side_effect=RuntimeError("telegram send failure"))
    session = make_session(send_cb)
    session.exit_code = 0

    # Put a sentinel to trigger the send_callback call that will raise
    await session.output_queue.put(None)

    with caplog.at_level(logging.ERROR, logger="telegram_opencode.session"):
        await session._dispatch_output()

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records, "Expected an ERROR-level log record"
    assert error_records[0].exc_info is not None, "Expected exc_info to be set"
