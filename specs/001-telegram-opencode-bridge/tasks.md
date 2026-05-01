# Tasks: Telegram OpenCode Bridge Bot

**Input**: Design documents from `/specs/001-telegram-opencode-bridge/`
**Feature branch**: `001-telegram-opencode-bridge`
**Status**: 40 of 40 tasks complete ✅ — all done (55 tests passing, ruff clean, mypy clean, 86% coverage)

## Format: `[ID] [P?] [Story?] Description with file path`

- **[x]**: Completed and verified (55/55 tests passing)
- **[ ]**: Not yet started
- **[P]**: Can run in parallel (writes to a different file; no in-flight dependencies)
- **[USn]**: Which user story this task delivers
  - **US1** — Submit a Coding Task (P1)
  - **US2** — Bidirectional Interaction (P2)
  - **US3** — Query Session Status (P3)
  - **US4** — Access Control Enforcement (P1)

---

## Phase 1: Project Scaffolding ✅

**Purpose**: Create the directory skeleton, dependency manifest, and environment template.

- [x] T001 Create directory structure: `src/telegram_opencode/` and `tests/`, each with `__init__.py`; source stubs `main.py`, `bot.py`, `session.py`, `config.py`
- [x] T002 [P] Create `pyproject.toml` at repo root: `[project]` with `name = "telegram-opencode"`, `requires-python = ">=3.11"`, `dependencies = ["python-telegram-bot>=21", "python-dotenv"]`; dev extras with `pytest`, `pytest-asyncio`, `ruff`, `black`, `mypy`, `pytest-cov`; `[tool.ruff]` `line-length = 100`, `select = ["E","F","I","UP","B","SIM"]`; `[tool.mypy]` `strict = true`, `python_version = "3.11"`; `[tool.pytest.ini_options]` `asyncio_mode = "auto"`, `testpaths = ["tests"]`, `addopts = "--cov=telegram_opencode --cov-fail-under=80"`
- [x] T003 [P] Create `.env.example` at repo root with `TELEGRAM_BOT_TOKEN=` (comment: "Bot API token from BotFather") and `AUTHORIZED_USER_IDS=` (comment: "Comma-separated integer Telegram user IDs permitted to use the bot")
- [x] T004 [P] Create `.gitignore` at repo root with entries: `.env`, `__pycache__/`, `*.pyc`, `.mypy_cache/`, `.pytest_cache/`, `dist/`, `*.egg-info/`, `.coverage`

**Checkpoint**: `pip install -e ".[dev]"` succeeds; `pytest` reports "no tests ran" without errors. ✅

---

## Phase 2: Config Module ✅

**Purpose**: Securely load and validate bot credentials from environment variables. Blocking prerequisite for all other phases — every module imports `Config`.

- [x] T005 [P] [US4] Write `tests/test_config.py`: `test_load_config_success` (env vars `TELEGRAM_BOT_TOKEN="abc"` + `AUTHORIZED_USER_IDS="111,222"` → `Config(bot_token="abc", authorized_user_ids=frozenset({111, 222}))`); `test_missing_token_raises` (absent/empty token → `ValueError`); `test_invalid_user_ids_raises` (absent/non-integer IDs → `ValueError`); `test_config_is_frozen` (field assignment → `FrozenInstanceError`)
- [x] T006 [US4] Implement `src/telegram_opencode/config.py`: `@dataclass(frozen=True) Config` with `bot_token: str` and `authorized_user_ids: frozenset[int]`; `load_config() -> Config` calls `load_dotenv()`, reads `TELEGRAM_BOT_TOKEN` (raises `ValueError` if blank), parses `AUTHORIZED_USER_IDS` splitting on commas and casting to `int` (raises `ValueError` on failure), returns `Config(...)`

**Checkpoint**: `pytest tests/test_config.py` — 4 tests pass. ✅

---

## Phase 3: Session Manager ✅

**Purpose**: Subprocess lifecycle, state machine, asyncio I/O pipeline, 1-second output buffering, 4096-char chunking, 30-minute inactivity timeout (FR-015), AWAITING\_INPUT prompt detection (NFR-006), auto-prime stdin (FR-003).

### 3a — Tests

- [x] T007 [US1] Write `tests/test_session.py` — data types: `test_session_state_members` (`SessionState` has exactly IDLE, RUNNING, AWAITING\_INPUT, COMPLETED, FAILED); `test_task_is_frozen`; `test_task_fields` (`description`, `task_type`, `working_directory`); `test_session_status_is_frozen`
- [x] T008 [US1] Write `tests/test_session.py` — `start()`: IDLE→RUNNING transition; subprocess called with `"opencode"` and `cwd=task.working_directory`; double-`start()` raises `InvalidStateError`; `_reader_task` and `_dispatcher_task` attributes set; auto-prime writes task description to stdin (`test_start_writes_task_description_to_stdin`)
- [x] T009 [US2] Write `tests/test_session.py` — `send_input()` state guards: succeeds in RUNNING and AWAITING\_INPUT; raises `InvalidStateError` in IDLE, COMPLETED, FAILED; stdin receives `b"text\n"`
- [x] T010 [US2] Write `tests/test_session.py` — `_read_output()`: lines pushed to `output_queue`; `None` sentinel after EOF; `exit_code` set; state→COMPLETED (exit 0) or FAILED (non-0); AWAITING\_INPUT entered on prompt-pattern lines (NFR-006); inactivity `TimeoutError` → FAILED + timeout notification (FR-015)
- [x] T011 [US2] Write `tests/test_session.py` — `_dispatch_output()`: 1-second buffer join (`test_dispatcher_joins_buffer_before_sentinel`); chunking at ≤4096 chars (`test_dispatcher_chunking`); failure notification after sentinel (`test_dispatcher_failure_notification`)
- [x] T012 [US1] Write `tests/test_session.py` — `terminate()`: SIGTERM → 5 s wait → SIGKILL on timeout; reader/dispatcher tasks cancelled; state→FAILED; no-op if already terminal (`test_terminate_noop_when_already_completed`)

### 3b — Implementation

- [x] T013 [US1] Implement data types in `src/telegram_opencode/session.py`: `SessionState` enum (5 members); `InvalidStateError`; `Task` and `SessionStatus` frozen dataclasses; `_detect_prompt(line: str) -> bool` helper (ends with `?`, `> `, or `: `); `_CHUNK_SIZE = 4096` module constant; `_INACTIVITY_TIMEOUT = 1800.0` module constant
- [x] T014 [US1] Implement `OpenCodeSession.__init__()` and `start()` in `src/telegram_opencode/session.py`: constructor initialises `state=IDLE`, `output_queue`, `recent_output` (deque maxlen=20), `process`, `started_at`, `ended_at`, `exit_code`, `_reader_task`, `_dispatcher_task`; `start()` launches `asyncio.create_subprocess_exec("opencode", cwd=..., stdout=PIPE, stderr=STDOUT, stdin=PIPE)`, sets `started_at`, transitions to RUNNING, writes `(task.description + "\n").encode()` to stdin + `drain()` (FR-003 auto-prime), creates reader and dispatcher asyncio Tasks
- [x] T015 [US2] Implement `send_input()` in `src/telegram_opencode/session.py`: guard RUNNING/AWAITING\_INPUT; write `(text + "\n").encode()` to stdin; `drain()`
- [x] T016 [US3] Implement `get_status()` in `src/telegram_opencode/session.py`: return `SessionStatus` snapshot from live fields
- [x] T017 [US1] Implement `terminate()` in `src/telegram_opencode/session.py`: SIGTERM + `asyncio.wait_for(process.wait(), 5.0)` + SIGKILL on timeout; cancel `_reader_task` and `_dispatcher_task`; state→FAILED; no-op if already terminal
- [x] T018 [US2] Implement `_read_output()` in `src/telegram_opencode/session.py`: loop `asyncio.wait_for(readline(), 1800.0)`; decode and append to `recent_output`; call `_detect_prompt()` to drive AWAITING\_INPUT/RUNNING transitions; on `TimeoutError` set state→FAILED + `ended_at` + notify user via `send_callback` (FR-015); on EOF get `exit_code`, set `ended_at`, set state (COMPLETED/FAILED), push `None` sentinel
- [x] T019 [US2] Implement `_dispatch_output()` in `src/telegram_opencode/session.py`: 1-second buffer via `asyncio.wait_for(queue.get(), 1.0)`; flush buffer on timeout or sentinel via `_send_chunks()`; send completion/failure notification after `None` sentinel; `_send_chunks()` splits at `_CHUNK_SIZE` (4096)

**Checkpoint**: `pytest tests/test_session.py` — all session tests pass (28 tests). ✅

---

## Phase 4: Bot Handlers ✅

**Purpose**: Telegram command and message handlers. Access control (US4), task submission (US1), status queries (US3), bidirectional input relay (US2).

### 4a — Tests

- [x] T020 [US4] Write `tests/test_bot.py` — `require_auth` decorator: `test_authorized_passes`, `test_unauthorized_silently_rejected` (no `reply_text`), `test_none_user_rejected`, `test_wraps_preserves_name`
- [x] T021 Write `tests/test_bot.py` — `help_handler`: reply contains `/start`, `/status`, `/cancel`, `/help`
- [x] T022 [US1] Write `tests/test_bot.py` — `start_handler` error paths: no args → `"Usage:"`; invalid task\_type → `"Invalid task type"`; directory not found → `"❌ Directory not found"`; path not a directory → `"❌ Path is not a directory"`; session already active → `"⚠️ A session is already running"`
- [x] T023 [US1] Write `tests/test_bot.py` — `start_handler` success: `Task` stored in `bot_data["sessions"]`; `session.start()` awaited; reply contains `"✅ Session started"` and task description
- [x] T024 [US3] Write `tests/test_bot.py` — `status_handler`: RUNNING reply contains state/task/directory/recent output; AWAITING\_INPUT reply contains `"AWAITING INPUT"` (underscore replaced by space, NFR-006 UX); no-session reply contains `"💤 No active session"`
- [x] T025 [US1] Write `tests/test_bot.py` — `cancel_handler`: active session → `session.terminate()` awaited, session removed, reply contains `"🛑 Session cancelled"` and task description; no session → `"ℹ️ No active session"`
- [x] T026 [US2] Write `tests/test_bot.py` — `message_handler`: RUNNING/AWAITING\_INPUT → `session.send_input()` awaited, no `reply_text`; no session → `"No active session"`; COMPLETED/FAILED → `"Session has ended"`

### 4b — Implementation

- [x] T027 [US4] Implement `require_auth` decorator in `src/telegram_opencode/bot.py`: `functools.wraps`; `logger.warning("Unauthorized access attempt from user_id=%s", user_id)` then `return` for unrecognised IDs (no details disclosed, FR-014)
- [x] T028 [P] Implement `help_handler` in `src/telegram_opencode/bot.py`: four-command listing per contract (`contracts/bot-commands.md`)
- [x] T029 [US1] Implement `start_handler` in `src/telegram_opencode/bot.py`: arg parsing; `Path.exists()` / `Path.is_dir()` / `os.access()` validation; session-conflict guard; `Task` + `OpenCodeSession` creation; `session.start()`; reply per contract success block
- [x] T030 [P] [US3] Implement `status_handler` in `src/telegram_opencode/bot.py`: retrieve session; format state name with `state.name.replace("_", " ")` (converts AWAITING\_INPUT → "AWAITING INPUT" per NFR-006 UX); multi-line reply per `/status` contract including recent output prefixed `"> "`
- [x] T031 [P] [US1] Implement `cancel_handler` in `src/telegram_opencode/bot.py`: `session.terminate()`; remove from sessions dict; reply `"🛑 Session cancelled.\nTask: ...\nExit: terminated by user"`
- [x] T032 [US2] Implement `message_handler` in `src/telegram_opencode/bot.py`: no-session reply; terminal-state reply; relay text to `session.send_input()` when RUNNING or AWAITING\_INPUT

**Checkpoint**: `pytest tests/test_bot.py` — all handler and decorator tests pass (21 tests). ✅

---

## Phase 5: Entry Point ✅

**Purpose**: Wire the PTB Application, register all handlers, configure graceful shutdown.

- [x] T033 Implement `src/telegram_opencode/main.py`: `load_config()`; `ApplicationBuilder().token(...).build()`; `bot_data["sessions"] = {}`; register all five handlers wrapped with `require_auth`; `post_shutdown` callback terminates all active sessions; `run_polling(drop_pending_updates=True)`; `if __name__ == "__main__": asyncio.run(main())`

**Checkpoint**: `python -m telegram_opencode.main` starts without import errors (exits with `ValueError` if `.env` absent — expected). ✅

---

## Phase 6: Integration Smoke Test ✅

**Purpose**: End-to-end validation with real module wiring; only `asyncio.create_subprocess_exec` and Telegram Bot API mocked.

- [x] T034 Write `tests/test_integration.py`: `test_full_session_lifecycle` (start → output forwarding → stdin relay → status → completion with mocked subprocess) and `test_cancel_terminates_session`

**Checkpoint**: `pytest tests/test_integration.py` — 2 smoke tests pass. ✅

---

## Phase 7: Contract Compliance Fixes

**Purpose**: Align three unsolicited notification messages in `session.py` to the exact formats defined in `contracts/bot-commands.md`, and add an explicit integration-level assertion for FR-003 auto-prime. No behaviour changes — output text and test assertions only.

- [x] T035 [US2] Fix timeout notification text
- [x] T036 [US2] Fix completion and failure notification texts in `_dispatch_output()` in `src/telegram_opencode/session.py`
- [x] T037 [US1] Add explicit auto-prime integration assertion to `test_full_session_lifecycle` in `tests/test_integration.py`

**Checkpoint**: `pytest tests/` — all 55+ tests still pass with updated assertions.

---

## Phase 8: Polish & Quality Validation

**Purpose**: Enforce style, strict typing, and ≥80% line coverage across all source and test files.

- [x] T038 [P] ruff check src/ tests/ — all clean
- [x] T039 [P] mypy --strict src/ — no issues found in 5 source files
- [x] T040 pytest --cov — 86% coverage, 80% threshold met (55/55 passing)

**Checkpoint**: `ruff check`, `mypy --strict`, and `pytest --cov` all exit with code 0.

---

## Dependencies

```
T001 → T002, T003, T004              # scaffold before config files
T002 → T005                          # pyproject.toml needed for pytest runner
T005 → T006                          # TDD: tests before implementation
T006 → T007                          # session tests import Config in fixtures
T007–T012 complete → T013            # all session tests written before implementation
T013 → T014                          # enums/dataclasses needed by OpenCodeSession
T014 → T015, T016, T017, T018, T019  # __init__/start fields used by all methods
T006 + T013–T019 complete → T020     # bot tests import Config + session types
T020–T026 complete → T027            # all bot tests before implementation
T027 → T028, T029, T030, T031, T032
T006 + T013–T032 complete → T033     # main.py wires all modules
T033 → T034                          # integration test runs real wiring
T034 → T035, T036, T037              # contract fixes after smoke test confirmed
T035, T036 → T037                    # notification text settled before asserting exact strings
T035, T036, T037 → T038, T039, T040  # polish after all fixes applied
T038 ∥ T039                          # ruff and mypy are independent tools
```

## Parallel Execution Opportunities

| Phase | Tasks that can run in parallel |
|-------|-------------------------------|
| Phase 1 | T002, T003, T004 (after T001) |
| Phase 3a | T007–T012 are sequential (all write `tests/test_session.py`) |
| Phase 3b | T015, T016, T017 independently after T014; T018 + T019 independently after T014 |
| Phase 4a | T020–T026 are sequential (all write `tests/test_bot.py`) |
| Phase 4b | T028, T030, T031 independently after T027 (different handlers) |
| Phase 7 | T035 ∥ T036 (different methods in `session.py`, different test functions) |
| Phase 8 | T038 ∥ T039 (ruff and mypy are independent; T040 runs after both) |

## Implementation Strategy — Delivery Increments

| Increment | Phases | Stories / Requirements delivered |
|-----------|--------|----------------------------------|
| MVP ✅ | 1 + 2 + 3b core + T027 + T029 + T031 + T033 | US4 + US1 (submit task, cancel) |
| +Output ✅ | T019 (dispatcher) + T015 (send\_input) + T032 | US2 full bidirectional I/O |
| +Status ✅ | T016 + T030 | US3 on-demand status |
| +Tests ✅ | T007–T012 (session) + T020–T026 (bot) + T034 (integration) | FR-013 automated coverage |
| +Contracts | T035 + T036 + T037 (Phase 7) | FR-015/FR-006/FR-003 exact message formats |
| Final | T038 + T039 + T040 (Phase 8) | NFR-004 ruff/mypy/coverage gate |
