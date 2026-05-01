"""OpenCode subprocess session manager with asyncio state machine and output buffering."""

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_INACTIVITY_TIMEOUT = 1800.0  # 30 minutes (FR-015)
_PROMPT_SUFFIXES = ("?", "> ", ": ")  # NFR-006


class SessionState(Enum):
    IDLE = auto()
    RUNNING = auto()
    AWAITING_INPUT = auto()
    COMPLETED = auto()
    FAILED = auto()


class InvalidStateError(Exception):
    """Raised when an operation is attempted in an invalid session state."""


@dataclass(frozen=True)
class Task:
    """Immutable value object describing a coding task."""

    description: str
    task_type: Literal["existing", "new"]
    working_directory: Path


@dataclass(frozen=True)
class SessionStatus:
    """Snapshot of the current session state for status reporting."""

    state: SessionState
    task_description: str | None
    task_type: str | None
    working_directory: str | None
    recent_output: list[str]
    started_at: datetime | None


_CHUNK_SIZE = 4096  # NFR-005: Telegram message size limit


def _detect_prompt(line: str) -> bool:
    """Return True if the line ends with a recognised interactive prompt pattern."""
    stripped = line.rstrip("\n")
    return any(stripped.endswith(suffix) for suffix in _PROMPT_SUFFIXES)


class OpenCodeSession:
    """Manages one OpenCode subprocess on behalf of a single authorized user."""

    def __init__(
        self,
        task: Task,
        send_callback: Callable[[str], Awaitable[None]],
    ) -> None:
        self.task = task
        self.send_callback = send_callback
        self.state: SessionState = SessionState.IDLE
        self.output_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.recent_output: deque[str] = deque(maxlen=20)
        self.process: asyncio.subprocess.Process | None = None
        self.started_at: datetime | None = None
        self.ended_at: datetime | None = None
        self.exit_code: int | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._dispatcher_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Launch the opencode subprocess and start reader/dispatcher tasks."""
        if self.state is not SessionState.IDLE:
            raise InvalidStateError(f"Cannot start session in state {self.state}")

        self.process = await asyncio.create_subprocess_exec(
            "opencode",
            cwd=self.task.working_directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.PIPE,
        )
        self.started_at = datetime.now(UTC)
        self.state = SessionState.RUNNING
        # FR-003: auto-prime OpenCode with the task description as first stdin line
        assert self.process.stdin is not None
        self.process.stdin.write((self.task.description + "\n").encode())
        await self.process.stdin.drain()
        self._reader_task = asyncio.create_task(self._read_output())
        self._dispatcher_task = asyncio.create_task(self._dispatch_output())

    async def send_input(self, text: str) -> None:
        """Write a line of text to the subprocess stdin."""
        if self.state not in {SessionState.RUNNING, SessionState.AWAITING_INPUT}:
            raise InvalidStateError(f"Cannot send input in state {self.state}")
        assert self.process is not None
        assert self.process.stdin is not None
        self.process.stdin.write((text + "\n").encode())
        await self.process.stdin.drain()

    def get_status(self) -> SessionStatus:
        """Return a snapshot of the current session state."""
        return SessionStatus(
            state=self.state,
            task_description=self.task.description,
            task_type=self.task.task_type,
            working_directory=str(self.task.working_directory),
            recent_output=list(self.recent_output),
            started_at=self.started_at,
        )

    async def terminate(self) -> None:
        """Forcefully terminate the subprocess and cancel background tasks."""
        if self.state in {SessionState.COMPLETED, SessionState.FAILED}:
            return

        assert self.process is not None
        self.process.terminate()

        try:
            await asyncio.wait_for(self.process.wait(), timeout=5.0)
        except TimeoutError:
            self.process.kill()

        if self._reader_task is not None:
            self._reader_task.cancel()
        if self._dispatcher_task is not None:
            self._dispatcher_task.cancel()

        self.state = SessionState.FAILED
        self.ended_at = datetime.now(UTC)
        logger.info("Session terminated (forced)")

    async def _read_output(self) -> None:
        """Read stdout/stderr lines and push them onto the output queue."""
        assert self.process is not None
        assert self.process.stdout is not None

        try:
            while True:
                try:
                    line_bytes = await asyncio.wait_for(
                        self.process.stdout.readline(),
                        timeout=_INACTIVITY_TIMEOUT,
                    )
                except TimeoutError:
                    # FR-015: 30-minute inactivity timeout
                    logger.warning(
                        "Session inactivity timeout after %s seconds",
                        _INACTIVITY_TIMEOUT,
                    )
                    self.state = SessionState.FAILED
                    self.ended_at = datetime.now(UTC)
                    await self.output_queue.put(None)
                    await self.send_callback(
                        f"⏱️ Session timed out after 30 minutes of inactivity.\n"
                        f"Task: {self.task.description}\n"
                        f"The session has been terminated."
                    )
                    return

                if line_bytes == b"":
                    break
                line = line_bytes.decode("utf-8", errors="replace")
                self.recent_output.append(line)
                # NFR-006: detect interactive prompt pattern to update state
                if _detect_prompt(line):
                    self.state = SessionState.AWAITING_INPUT
                elif self.state is SessionState.AWAITING_INPUT:
                    self.state = SessionState.RUNNING
                await self.output_queue.put(line)
        except Exception:  # FR-016: log unexpected errors with traceback
            logger.error("Unexpected error in _read_output", exc_info=True)
            self.state = SessionState.FAILED
            self.ended_at = datetime.now(UTC)
            await self.output_queue.put(None)
            return

        self.exit_code = await self.process.wait()
        self.ended_at = datetime.now(UTC)
        self.state = SessionState.COMPLETED if self.exit_code == 0 else SessionState.FAILED
        logger.info("Session ended: exit_code=%s state=%s", self.exit_code, self.state)
        await self.output_queue.put(None)

    async def _dispatch_output(self) -> None:
        """Buffer output for 1 s then forward chunks to the Telegram callback."""
        buffer: list[str] = []

        try:
            while True:
                try:
                    item = await asyncio.wait_for(self.output_queue.get(), timeout=1.0)
                except TimeoutError:
                    if buffer:
                        await self._send_chunks("\n".join(s.rstrip("\n") for s in buffer))
                        buffer.clear()
                    continue

                if item is None:
                    if buffer:
                        await self._send_chunks("\n".join(s.rstrip("\n") for s in buffer))
                        buffer.clear()
                    if self.exit_code == 0:
                        await self.send_callback(
                            f"✅ Session completed successfully.\nTask: {self.task.description}"
                        )
                    else:
                        await self.send_callback(
                            f"❌ Session ended with an error.\n"
                            f"Task: {self.task.description}\n"
                            f"Exit code: {self.exit_code}"
                        )
                    break

                buffer.append(item)
        except Exception:  # FR-016: log unexpected errors with traceback
            logger.error("Unexpected error in _dispatch_output", exc_info=True)

    async def _send_chunks(self, text: str) -> None:
        """Split text into ≤4096-char chunks and forward each to send_callback."""
        for i in range(0, len(text), _CHUNK_SIZE):
            await self.send_callback(text[i : i + _CHUNK_SIZE])
