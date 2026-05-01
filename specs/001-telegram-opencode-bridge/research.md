# Research: Telegram OpenCode Bridge Bot

**Phase**: 0 — Outline & Research  
**Branch**: `001-telegram-opencode-bridge`  
**Date**: 2026-05-01

All items that required investigation before design could proceed are recorded here with decisions, rationale, and alternatives considered.

---

## R-001: python-telegram-bot v21+ Async Application Model

**Decision**: Use `Application` (PTB v21 native async) with `ApplicationBuilder`, long-polling via `Application.run_polling()`. Register handlers via `application.add_handler()`.

**Rationale**: PTB v21 is a full async rewrite. `run_polling()` internally manages the event loop, threaded executor, and graceful shutdown. It integrates cleanly with asyncio tasks spawned for subprocess I/O. Using the `Application` model future-proofs the bot against PTB's deprecation of legacy synchronous wrappers.

**Key patterns**:
```python
from telegram.ext import Application, CommandHandler, MessageHandler, filters

app = ApplicationBuilder().token(config.bot_token).build()
app.add_handler(CommandHandler("start", start_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
app.run_polling()
```

**Alternatives considered**:
- `Updater` (deprecated in PTB v20+) — rejected; removed in v21.
- Webhook mode — rejected; adds deployment complexity (public HTTPS endpoint required) with no benefit for a single-operator bot.

---

## R-002: asyncio.create_subprocess_exec for Non-Blocking OpenCode I/O

**Decision**: Use `asyncio.create_subprocess_exec` with `stdout=asyncio.subprocess.PIPE`, `stderr=asyncio.subprocess.STDOUT` (merged), and `stdin=asyncio.subprocess.PIPE`. Read lines with `process.stdout.readline()` in a dedicated `asyncio.Task`.

**Rationale**: `asyncio.create_subprocess_exec` avoids blocking the event loop (unlike `subprocess.Popen`). Merging stderr into stdout simplifies routing — all session output goes through one queue. A single reader task per session is sufficient; the queue decouples reading from delivery without requiring threads.

**Key patterns**:
```python
process = await asyncio.create_subprocess_exec(
    "opencode", *args,
    cwd=working_dir,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.STDOUT,
    stdin=asyncio.subprocess.PIPE,
)
```

**Alternatives considered**:
- `asyncio.create_subprocess_shell` — rejected; shell=True with user-supplied paths is a command injection risk.
- `subprocess.Popen` in `ThreadPoolExecutor` — rejected; more complex, harder to test, no real advantage over native async API.
- Separate stdout/stderr pipes — rejected; doubles routing complexity for no UX gain (both streams go to the user anyway).

---

## R-003: asyncio.Queue for Output Routing

**Decision**: The session manager maintains a single `asyncio.Queue[str | None]` per session. The subprocess reader pushes lines; a separate `output_dispatcher` task pops lines and applies buffering. `None` is the sentinel for end-of-stream.

**Rationale**: Queue decouples reader speed from Telegram send rate. The dispatcher can implement the 1-second buffering window without blocking the reader. This is the standard producer/consumer pattern for async I/O bridges.

**Queue lifetime**: Created when session starts, drained and discarded when session ends (COMPLETED or FAILED state).

**Alternatives considered**:
- Calling `bot.send_message` directly from the reader coroutine — rejected; tightly couples I/O reading to Telegram delivery; any Telegram API slowness would stall output reading.
- `asyncio.Event` + shared buffer — rejected; more complex synchronization; Queue is simpler and already handles the producer/consumer contract.

---

## R-004: Output Buffering — 1-Second Collect Window

**Decision**: The `output_dispatcher` task uses `asyncio.wait_for` with a 1-second timeout on `queue.get()`. It accumulates lines until the timeout fires, then joins them into a single message and sends to Telegram. If accumulated content exceeds 4096 chars, it is split into chunks before sending.

**Rationale**: Telegram's Bot API has a rate limit of approximately 30 messages/second globally and 1 message/second per chat. Without buffering, a verbose OpenCode output burst would trigger 429 rate-limit errors. A 1-second window balances responsiveness (still well within the 3-second NFR) against rate-limit risk.

**Chunk size**: 4096 characters (Telegram `sendMessage` hard limit). Long lines are split at the limit boundary; no mid-word truncation is attempted since code output is not natural language.

**Alternatives considered**:
- Fixed-count buffering (e.g., every 5 lines) — rejected; count-based batching behaves poorly for both very short and very long lines.
- Telegram `editMessage` to update a single message — rejected; requires tracking message IDs; complex retry logic; doesn't reduce API calls meaningfully.

---

## R-005: Session State Machine

**Decision**: Define a `SessionState` enum with values: `IDLE`, `RUNNING`, `AWAITING_INPUT`, `COMPLETED`, `FAILED`. The `OpenCodeSession` class holds the current state and enforces valid transitions.

**State transition table**:

| From | Event | To |
|------|-------|----|
| IDLE | `start()` called | RUNNING |
| RUNNING | Subprocess produces prompt-like output | AWAITING_INPUT |
| RUNNING | Subprocess exits with code 0 | COMPLETED |
| RUNNING | Subprocess exits with non-zero code | FAILED |
| AWAITING_INPUT | User reply delivered to stdin | RUNNING |
| COMPLETED / FAILED | (terminal, no transitions) | — |

**Prompt detection heuristic**: A line ending in `?` or containing common prompt patterns (`[y/N]`, `>>`, `Enter`) is treated as AWAITING_INPUT. This is a best-effort heuristic; users can always reply even when state remains RUNNING.

**Rationale**: Explicit state machine makes status reporting accurate and prevents illegal operations (e.g., sending input to a COMPLETED session). States map directly to FR-007/FR-008 status responses.

**Alternatives considered**:
- Boolean `is_running` flag — rejected; too coarse; cannot distinguish AWAITING_INPUT from RUNNING, which matters for status reporting.
- External state management (e.g., Redis) — rejected; spec explicitly calls for in-memory only; single-process; no persistence requirement.

---

## R-006: Authorization Middleware

**Decision**: Implement a `require_auth` decorator factory that wraps PTB handler coroutines. It extracts `update.effective_user.id` and checks it against `config.authorized_user_ids` (a `frozenset[int]`). If not authorized, it logs the attempt (user ID + timestamp, no message content) and returns without processing. No reply is sent to the unauthorized user (per FR-014: "without disclosing any system information").

**Implementation pattern**:
```python
from functools import wraps
from typing import Callable, Awaitable
from telegram import Update
from telegram.ext import ContextTypes

def require_auth(config: Config):
    def decorator(handler: Callable[..., Awaitable[None]]):
        @wraps(handler)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            user_id = update.effective_user.id if update.effective_user else None
            if user_id not in config.authorized_user_ids:
                return  # silent rejection per FR-014
            await handler(update, context)
        return wrapper
    return decorator
```

**Rationale**: Decorator-based authorization is composable and easy to test. Injecting `config` avoids global state. Silent rejection (no reply) satisfies FR-014.

**Alternatives considered**:
- PTB `filters.User(user_ids=[...])` filter — rejected; only works as a handler filter, cannot be reused across command handlers without boilerplate; less testable.
- Global middleware via `Application.add_handler` with a shared filter — considered but rejected in favor of the explicit decorator since it makes authorization visible at the handler definition site.

---

## R-007: Graceful Shutdown — SIGTERM Handling

**Decision**: Register a `signal.signal(signal.SIGTERM, shutdown_handler)` in `main.py` that calls `Application.stop()` and, if a session is active, terminates the OpenCode subprocess via `process.terminate()` followed by `process.wait()` with a 5-second timeout, then `process.kill()` if it hasn't exited.

**Rationale**: PTB's `run_polling()` handles SIGINT (Ctrl+C) natively but SIGTERM (systemd/Docker stop) needs explicit wiring. Terminating the subprocess prevents orphaned `opencode` processes. A `FAILED` state notification is sent to the user if a session is active when shutdown occurs (best-effort — Telegram connection may already be closing).

**Alternatives considered**:
- `atexit` handler — rejected; does not fire on SIGTERM.
- Relying solely on PTB's built-in signal handling — rejected; PTB handles SIGTERM in newer versions but the subprocess cleanup must be explicit regardless.

---

## R-008: pytest-asyncio Patterns for Testing Async Handlers

**Decision**: Use `pytest-asyncio` with `asyncio_mode = "auto"` (configured in `pyproject.toml`). Mock PTB `Update` and `ContextTypes.DEFAULT_TYPE` with `unittest.mock.AsyncMock` for `send_message` and similar coroutines. Mock `asyncio.create_subprocess_exec` to return a `MagicMock` with async `communicate()` and `stdout.readline()`.

**Key fixture patterns**:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.fixture
def mock_update():
    update = MagicMock()
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()
    return update

@pytest.fixture
def mock_context():
    return MagicMock()
```

**Rationale**: `asyncio_mode = "auto"` eliminates decorator boilerplate on every test. `AsyncMock` correctly handles `await` calls in assertions. This approach avoids spinning up a real Telegram connection in unit tests.

**Alternatives considered**:
- `pytest-trio` — rejected; project uses asyncio, not trio.
- Integration tests against real Telegram API — deferred to manual QA; automated tests are unit-level with mocks.

---

## R-009: pyproject.toml Tool Configuration

**Decision**: Single `pyproject.toml` at the repository root manages all tool configuration:

```toml
[tool.ruff]
line-length = 100
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.black]
line-length = 100

[tool.mypy]
strict = true
python_version = "3.11"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Rationale**: Centralizing tool config in `pyproject.toml` is the modern Python standard. `ruff` covers import sorting (I), pyupgrade (UP), flake8-bugbear (B), and simplify (SIM) in addition to PEP 8, reducing the number of tools needed. `mypy --strict` enforces full type annotation as required by the constitution.

---

## R-010: Directory Path Validation (FR-002)

**Decision**: Validate user-supplied directory paths in the handler before starting a session:
1. `Path(user_path).resolve()` to normalize and dereference symlinks.
2. Check `resolved_path.exists()` — if not, reply with "Directory not found" and abort.
3. Check `resolved_path.is_dir()` — if not, reply with "Path is not a directory" and abort.
4. Attempt `os.access(resolved_path, os.R_OK | os.X_OK)` — if denied, reply with "Directory is not accessible" and abort.

**Path traversal risk mitigation**: The path is user-supplied text and must not be interpreted as a shell argument. `asyncio.create_subprocess_exec` passes it as a direct `cwd` argument (not shell-interpolated), eliminating traversal via shell metacharacters. The resolved absolute path is logged for auditing.

**Alternatives considered**:
- Allowlist of permitted directories — rejected; spec does not define an allowlist; the bot is operator-owned and the authorized user is trusted to supply valid paths.

---

## Summary of Resolved Decisions

| ID | Topic | Decision |
|----|-------|---------|
| R-001 | PTB async model | `Application` + `run_polling()` |
| R-002 | Subprocess I/O | `asyncio.create_subprocess_exec`, merged stdout/stderr |
| R-003 | Output routing | `asyncio.Queue[str \| None]` with sentinel |
| R-004 | Output buffering | 1-second collect window; 4096-char Telegram chunks |
| R-005 | Session state | Enum-based state machine: IDLE/RUNNING/AWAITING_INPUT/COMPLETED/FAILED |
| R-006 | Authorization | `require_auth` decorator; silent rejection; `frozenset[int]` user IDs |
| R-007 | Graceful shutdown | SIGTERM → `Application.stop()` + subprocess `terminate`/`kill` |
| R-008 | Testing patterns | `pytest-asyncio` auto mode; `AsyncMock` for PTB, `patch` for subprocess |
| R-009 | Tool config | `pyproject.toml`: ruff + black (100), mypy strict, pytest auto |
| R-010 | Path validation | `Path.resolve()` + `exists()` + `is_dir()` + `os.access()` |
