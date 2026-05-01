# Data Model: Telegram OpenCode Bridge Bot

**Phase**: 1 — Design & Contracts  
**Branch**: `001-telegram-opencode-bridge`  
**Date**: 2026-05-01

---

## Entities

### 1. `Config` (config.py)

Immutable settings loaded once at startup from environment variables via `python-dotenv`.

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `bot_token` | `str` | `TELEGRAM_BOT_TOKEN` | Telegram Bot API token |
| `authorized_user_ids` | `frozenset[int]` | `AUTHORIZED_USER_IDS` (comma-separated integers) | Set of Telegram user IDs permitted to use the bot |

**Validation rules**:
- `bot_token` must be non-empty; raise `ValueError` at startup if missing.
- `AUTHORIZED_USER_IDS` must contain at least one valid integer; raise `ValueError` if empty or unparseable.
- Both values sourced exclusively from environment variables; never defaulted to hardcoded values.

**Immutability**: `Config` is a frozen `dataclass` (`@dataclass(frozen=True)`). Authorized user IDs are a `frozenset` to prevent accidental mutation and to make membership checks O(1).

---

### 2. `SessionState` (session.py)

Enum representing the lifecycle of an OpenCode subprocess session.

```python
from enum import Enum, auto

class SessionState(Enum):
    IDLE = auto()             # No subprocess running
    RUNNING = auto()          # Subprocess active, processing
    AWAITING_INPUT = auto()   # Subprocess waiting for user reply
    COMPLETED = auto()        # Subprocess exited with code 0
    FAILED = auto()           # Subprocess exited with non-zero code or crashed
```

**Valid state transitions**:

```
IDLE ──start()──► RUNNING ──exit(0)──► COMPLETED
                     │
                     ├──exit(non-0)──► FAILED
                     │
                     ├──inactivity timeout (30 min)──► FAILED (user notified)
                     │
                     ├──prompt detected──► AWAITING_INPUT
                     │                          │
                     └──────────────────────────┘ (reply sent → back to RUNNING)
```

Terminal states: `COMPLETED`, `FAILED`. Sessions in terminal states cannot be restarted; a new `OpenCodeSession` object must be created.

---

### 3. `Task` (session.py)

A value object representing the coding task submitted by the user.

| Field | Type | Description |
|-------|------|-------------|
| `description` | `str` | The task text as provided by the user |
| `task_type` | `Literal["existing", "new"]` | Whether the task applies to an existing project or creates a new one |
| `working_directory` | `Path` | Resolved absolute path to the project directory (validated before session creation) |

**Validation rules**:
- `description` must be non-empty.
- `working_directory` must exist, be a directory, and be accessible (checked in handler, not in `Task`; `Task` stores already-validated paths).

**Implementation**: `@dataclass(frozen=True)` — immutable value object.

---

### 4. `OpenCodeSession` (session.py)

The central stateful object managing one OpenCode subprocess invocation on behalf of a single authorized user.

| Field | Type | Description |
|-------|------|-------------|
| `task` | `Task` | The task this session is executing |
| `state` | `SessionState` | Current lifecycle state |
| `process` | `asyncio.subprocess.Process \| None` | The running subprocess handle |
| `output_queue` | `asyncio.Queue[str \| None]` | Lines from stdout/stderr; `None` = end-of-stream sentinel |
| `recent_output` | `collections.deque[str]` | Rolling buffer of the last N output lines (default N=20) for status reports |
| `started_at` | `datetime \| None` | Timestamp when session started (UTC) |
| `ended_at` | `datetime \| None` | Timestamp when session ended (UTC) |
| `exit_code` | `int \| None` | Subprocess exit code; set on termination |
| `_inactivity_timeout` | `float` | Seconds before the reader declares inactivity; hardcoded `1800.0` (30 minutes, FR-015); not a configurable field |

**Key methods**:

| Method | Signature | Description |
|--------|-----------|-------------|
| `start` | `async def start() -> None` | Launch subprocess; immediately write `(task.description + "\n").encode()` to stdin and call `drain()` (auto-prime, FR-003); spawn reader task and dispatcher task; transition IDLE → RUNNING |
| `send_input` | `async def send_input(text: str) -> None` | Write `text + "\n"` to subprocess stdin; valid only in RUNNING or AWAITING_INPUT states |
| `terminate` | `async def terminate() -> None` | Send SIGTERM to subprocess; wait up to 5s; SIGKILL if needed; transition to FAILED |
| `get_status` | `def get_status() -> SessionStatus` | Return a snapshot of current state, task, and recent output |
| `_detect_prompt` | Module-level `def _detect_prompt(line: str) -> bool` | Returns `True` when `line` ends with `?`, `> `, or `: `; called per forwarded line to drive RUNNING → AWAITING_INPUT transition (NFR-006); AWAITING_INPUT reverts to RUNNING on the next received output line |
| `_send_chunks` | `async def _send_chunks(text: str) -> None` | Splits `text` into sequential ≤`_CHUNK_SIZE`-char pieces and sends each as a separate Telegram message; `_CHUNK_SIZE = 4096` is a module-level constant (NFR-005) |

**Concurrency model**:
- `_reader_task`: asyncio Task — reads lines from `process.stdout` using `asyncio.wait_for(readline(), timeout=1800.0)`; calls `_detect_prompt()` on each line to drive AWAITING_INPUT transitions; pushes lines to `output_queue`; on `TimeoutError` sets `state = FAILED`, notifies user via `send_callback`, and breaks (FR-015)
- `_dispatcher_task`: asyncio Task — pops from `output_queue`, buffers for 1 second, then calls `_send_chunks()` to split output into ≤4096-char Telegram messages (NFR-005)

Both tasks are created when `start()` is called. Both are cancelled in `terminate()` and when the subprocess exits.

---

### 5. `SessionStatus` (session.py)

A snapshot value object returned by `OpenCodeSession.get_status()`, sent to the user in response to a status inquiry (FR-007, FR-008).

| Field | Type | Description |
|-------|------|-------------|
| `state` | `SessionState` | Current state at the moment of the snapshot |
| `task_description` | `str \| None` | Task description if a session has been started |
| `task_type` | `str \| None` | `"existing"` or `"new"` (presentation labels "Existing project"/"New project" are applied in bot.py handlers) |
| `working_directory` | `str \| None` | Absolute path of the session's working directory |
| `recent_output` | `list[str]` | Last N output lines (copy of the rolling buffer) |
| `started_at` | `datetime \| None` | When the session started |

**Implementation**: `@dataclass(frozen=True)` — immutable snapshot.

---

## In-Memory State Layout

```
BotApplication (singleton)
└── session_store: dict[int, OpenCodeSession]
      └── key: telegram user_id (int)
          value: OpenCodeSession instance
                 └── one per authorized user, at most one active session at a time
```

`session_store` is a plain `dict[int, OpenCodeSession]` stored in PTB's `bot_data["sessions"]`, initialised in `main.py` and accessed in handlers via `context.bot_data`. There is no module-level global — the store lives exclusively inside the PTB Application's `bot_data` dict.

---

## State Machine Diagram

```
┌────────┐
│  IDLE  │◄─────────────────────────────────────────────────────┐
└───┬────┘                                                       │
    │ /start <task>                                              │ (new session created
    ▼                                                            │  for next task)
┌─────────┐  prompt detected  ┌─────────────────┐              │
│ RUNNING │──────────────────►│ AWAITING_INPUT  │              │
│         │◄──────────────────│                 │              │
└────┬────┘  reply delivered  └─────────────────┘              │
     │                                                           │
     ├──────────── exit code 0 ──────────────────► COMPLETED ───┤
     │                                                           │
     ├──────────── exit non-0 / crash ──────────► FAILED ───────┘
     │
     └──────────── inactivity timeout (30 min) ─► FAILED (+ notify user)
```

---

## Validation Rules Summary

| Entity | Field | Rule |
|--------|-------|------|
| `Config` | `bot_token` | Non-empty string; sourced from env only |
| `Config` | `authorized_user_ids` | At least one valid integer; sourced from env only |
| `Task` | `description` | Non-empty string |
| `Task` | `working_directory` | Must exist, be a directory, be accessible (checked pre-`Task` creation) |
| `OpenCodeSession` | `send_input` | Only callable in `RUNNING` or `AWAITING_INPUT` states; raise `InvalidStateError` otherwise |
| `OpenCodeSession` | `start` | Only callable in `IDLE` state; raise `InvalidStateError` if already started |

---

## Post-Design Constitution Re-check

| Principle | Status | Design evidence |
|-----------|--------|----------------|
| I. Python Expertise | PASS | Frozen dataclasses, type hints on all entities, `frozenset`, `deque`, `Path`, `Literal` — all idiomatic Python 3.11 |
| II. Deep Thinking | PASS | State machine formally documented; concurrency model explicit; edge cases (terminal states, concurrent start) handled |
| III. Test-Before-Delivery | PASS | Each entity has testable boundaries; `OpenCodeSession` methods raise on illegal state (easy to unit test) |
| IV. Code Quality | PASS | `OpenCodeSession` decomposed into reader + dispatcher tasks; `SessionStatus` is a pure value object; no cross-entity mutation |
| V. Security | PASS | `Config` is immutable after load; `working_directory` validated before use; no user data interpreted as code |

**Gate decision**: Phase 1 design compliant. Proceed to contracts and quickstart.
