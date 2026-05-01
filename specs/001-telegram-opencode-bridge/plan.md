# Implementation Plan: Telegram OpenCode Bridge Bot

**Branch**: `001-telegram-opencode-bridge` | **Date**: 2026-05-01 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-telegram-opencode-bridge/spec.md`

## Summary

Build an async Python service that bridges authorized Telegram users to live OpenCode CLI sessions running on the host machine. Users submit coding tasks via Telegram commands; the bot spawns an `opencode` subprocess scoped to the given directory, immediately writes the task description as the first stdin line to auto-prime OpenCode (FR-003), then streams all stdout/stderr output back to Telegram in ≤4096-character chunks (`_CHUNK_SIZE = 4096`, NFR-005) with 1-second buffering to avoid rate limits, and pipes user replies back as stdin. A session state machine (IDLE → RUNNING → AWAITING_INPUT → COMPLETED/FAILED) tracks lifecycle; AWAITING_INPUT is entered when the last forwarded output line matches a prompt pattern (`?`, `> `, or `: `) via a `_detect_prompt()` helper in `session.py` (NFR-006). A 30-minute inactivity timeout (FR-015) wraps each `readline()` call with `asyncio.wait_for(..., timeout=1800.0)`; on `TimeoutError` the session transitions to FAILED and the user is notified. All modules emit structured log entries via `logging.getLogger(__name__)` at INFO level to stderr, with ERROR-level tracebacks on unexpected errors (FR-016). An authorization decorator ensures only configured Telegram user IDs can interact with the bot.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: `python-telegram-bot` v21+ (async PTB Application), `python-dotenv`
**Storage**: N/A — in-memory session state (single `OpenCodeSession` per authorized user, lost on restart)
**Testing**: `pytest` + `pytest-asyncio`; `unittest.mock` for subprocess and Telegram API mocking
**Target Platform**: Linux/macOS developer server (wherever `opencode` CLI is installed)
**Project Type**: Long-running async service/daemon
**Performance Goals**: Output forwarding ≤ 3 s (NFR-001); reply → session input ≤ 3 s (NFR-002); status response ≤ 3 s (SC-004)
**Constraints**: Single session per authorized user; no database; Telegram message cap 4096 chars (`_CHUNK_SIZE = 4096` module-level constant in `session.py`, NFR-005); in-process state only; session auto-prime writes task description to stdin immediately after subprocess start (FR-003); AWAITING_INPUT triggered by `_detect_prompt(line)` on `?` / `> ` / `: ` line endings (NFR-006); 30-minute inactivity timeout via `asyncio.wait_for` → state FAILED + user notification (FR-015); structured logging via `logging.getLogger(__name__)` in every module (FR-016)
**Scale/Scope**: Small operator-managed deployment (handful of pre-configured authorized user IDs, 1 active session per user)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Python Expertise | PASS | Python 3.11+, type hints throughout, PEP 8 via ruff, black formatting; asyncio stdlib used before third-party; `python-telegram-bot` justified as the canonical Telegram async library |
| II. Deep Thinking Before Acting | PASS | Phase 0 research.md and Phase 1 design artifacts required before any code; state machine and queue design documented in research |
| III. Test-Before-Delivery | PASS | pytest + pytest-asyncio planned; all handlers, session manager, and config module require tests before implementation is considered done |
| IV. Code Quality | PASS | State machine enforces single-responsibility; asyncio.Queue decouples output production from delivery; authorization is a decorator (composition); no global mutable state (config injected) |
| V. Security | PASS | Credentials loaded exclusively from `.env` via python-dotenv; `.env` must be in `.gitignore`; authorization decorator rejects all unrecognized user IDs without disclosing system information; all external inputs (paths, task descriptions) validated at entry points |

**Gate decision**: All principles pass. No violations. Proceed to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/001-telegram-opencode-bridge/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── bot-commands.md
└── tasks.md             # Phase 2 output (speckit.tasks — not created here)
```

### Source Code (repository root)

```text
src/
└── telegram_opencode/
    ├── __init__.py
    ├── main.py           # Entry point: wires Application, registers handlers, starts polling
    ├── bot.py            # PTB command/message handlers + authorization decorator
    ├── session.py        # OpenCodeSession: subprocess lifecycle + asyncio.Queue I/O; _detect_prompt() helper; _CHUNK_SIZE = 4096; 30-min inactivity timeout
    └── config.py         # Settings dataclass loaded from environment via python-dotenv

tests/
├── __init__.py
├── test_bot.py           # Handler unit tests (mocked PTB Update/Context)
├── test_session.py       # Session manager unit tests (mocked subprocess)
└── test_config.py        # Config loading unit tests (mocked env vars)

pyproject.toml            # Project metadata, dependency pinning, ruff/black/mypy config
.env.example              # Documented template for required environment variables
```

**Structure Decision**: Single-project layout (Option 1). The service is a single deployable daemon with clear internal module boundaries: handlers, session manager, config. No separate frontend or secondary service warranted.

## Spec Clarifications Applied

The following clarifications from the 2026-05-01 session are incorporated throughout this plan, data-model.md, and contracts/bot-commands.md:

| # | Requirement | Change |
|---|-------------|--------|
| 1 | FR-003 updated | `session.start()` writes `(task.description + "\n").encode()` to stdin and calls `drain()` before returning (auto-prime). No manual first message from the user is needed after the `/start` confirmation. |
| 2 | NFR-006 new | AWAITING_INPUT is entered when the last forwarded output line ends with `?`, `> `, or `: `. A private `_detect_prompt(line: str) -> bool` helper in `session.py` encapsulates this logic. Transition back to RUNNING on the next output line. |
| 3 | FR-015 new | 30-minute inactivity timeout. `_reader_task` wraps each `readline()` in `asyncio.wait_for(..., timeout=1800.0)`. On `TimeoutError`: set `state = FAILED`, invoke `send_callback` with a timeout notification message, break the read loop. |
| 4 | NFR-005 clarified | Output splitting at ≤4096 chars per chunk is already implemented in `_send_chunks`. Confirmed constant: `_CHUNK_SIZE = 4096` (module-level in `session.py`). |
| 5 | FR-016 new | Structured logging: each module calls `logging.getLogger(__name__)`. Key events logged: bot start/stop, session start/end (task type + directory), unauthorized access attempt (user_id only, no details), unexpected errors (ERROR level with `exc_info=True`). |

## Complexity Tracking

> No constitution violations — table not required.
