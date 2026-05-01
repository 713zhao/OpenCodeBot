# Feature Specification: Telegram OpenCode Bridge Bot

**Feature Branch**: `001-telegram-opencode-bridge`  
**Created**: 2026-05-01  
**Status**: Draft  
**Input**: User description: "Build a Telegram Programmer Bot that lets users control OpenCode sessions remotely through Telegram."

## Clarifications

### Session 2026-05-01

- Q: How does the task description reach the OpenCode CLI process? → A: The bot immediately writes the task description as the first stdin line after the subprocess starts (auto-priming). OpenCode is not passed any CLI arguments; only `cwd` is set.
- Q: What triggers the AWAITING_INPUT session state? → A: The session transitions to AWAITING_INPUT when the most-recently forwarded output line ends with a prompt pattern (`?`, `> `, or `: `). It returns to RUNNING on the next output line received.
- Q: What is the session hang/timeout policy? → A: A 30-minute inactivity timeout applies. If no stdout/stderr output is received for 30 minutes the bot sends a timeout notification to the user and terminates the session with FAILED state.
- Q: Should long output be split across multiple messages or truncated? → A: Split into ≤4096-character chunks in order (no truncation); each chunk is sent as a separate Telegram message.
- Q: What observability/logging is required? → A: Python `logging` to stderr at INFO level. Key events logged: bot start/stop, session start/end (with task type and directory), unauthorized access attempts (user ID only, no details), and unexpected errors (with traceback at ERROR level).

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Submit a Coding Task (Priority: P1)

An authorized user wants to delegate a coding task to OpenCode without being present at the machine. They open the Telegram bot, describe their task, specify whether they are working on an existing project (providing its local path) or starting a new project (providing a target folder), and the bot acknowledges and begins the session. The user receives a confirmation that work has started.

**Why this priority**: This is the entry point to all other functionality. Without task submission, nothing else in the feature operates. It delivers immediate value: users can kick off coding work remotely.

**Independent Test**: Can be tested by sending a task message to the bot and verifying a session is started in the correct directory, with a confirmation reply returned to the user. No bidirectional communication or status polling is required to confirm success.

**Acceptance Scenarios**:

1. **Given** an authorized user is in a Telegram chat with the bot, **When** they submit a task with task type `existing` and a valid local directory path, **Then** the bot confirms the session has started, scoped to that directory.
2. **Given** an authorized user submits a task to create a new project specifying a target folder, **When** the folder exists and is accessible, **Then** the bot confirms the session has started in that folder.
3. **Given** an authorized user submits a task with an invalid or inaccessible directory path, **When** the bot attempts to scope the session, **Then** the bot replies with a clear error message and does not start a session.
4. **Given** a session is already active for the user, **When** they attempt to submit a new task, **Then** the bot informs them a session is already running and asks whether to cancel it or wait.

---

### User Story 2 - Interact Bidirectionally During a Session (Priority: P2)

While OpenCode is running, it may produce questions, request clarification, or encounter errors requiring user direction. The authorized user receives these messages via Telegram exactly as they appear in the running session. The user replies in the Telegram chat, and their response is fed directly into the OpenCode session, allowing the work to continue without the user being at the keyboard.

**Why this priority**: This is what makes the bot a true remote control rather than a simple fire-and-forget launcher. Without this, users cannot guide OpenCode through multi-step or ambiguous tasks. It directly enables productive, interactive remote coding sessions.

**Independent Test**: Can be tested by starting a session that immediately prompts for input, verifying the prompt is forwarded to Telegram, sending a reply, and confirming the reply is delivered to the session and work continues.

**Acceptance Scenarios**:

1. **Given** an active OpenCode session produces a message or prompt, **When** the message is emitted by the session, **Then** the bot forwards it to the authorized user in Telegram within an acceptable delay.
2. **Given** the bot has forwarded a session prompt to the user, **When** the user replies via Telegram, **Then** the reply is passed as input into the OpenCode session.
3. **Given** an active session emits a non-interactive status message or log output, **When** the output is produced, **Then** the bot forwards it to the user so they remain informed.
4. **Given** an active session terminates (successfully or with an error), **When** termination occurs, **Then** the bot notifies the user that the session has ended, including the final status.

---

### User Story 3 - Query Session Status (Priority: P3)

At any time, an authorized user wants to know what is happening in their running OpenCode session without waiting for the bot to send an unsolicited update. They send a status command via Telegram, and the bot replies with a summary of the current task, the current session state, and the most recent output or activity observed.

**Why this priority**: Status enquiry gives users on-demand visibility and confidence that work is progressing. It complements bidirectional communication and is independently valuable for long-running tasks where the user expects to check in periodically.

**Independent Test**: Can be tested by starting a session, waiting a short period, sending a status request, and verifying the response contains the task description, a current phase indicator, and recent output. No bidirectional message exchange is needed.

**Acceptance Scenarios**:

1. **Given** an active session is running, **When** the authorized user sends a status inquiry, **Then** the bot replies with the current task description, current session state, and recent output.
2. **Given** no session is active, **When** the user requests status, **Then** the bot replies that no task is currently running.
3. **Given** a session just started, **When** the user requests status before any output is produced, **Then** the bot reports the task is initializing and lists the task details.

---

### User Story 4 - Access Control Enforcement (Priority: P1)

Only users whose identifiers have been pre-configured as authorized may interact with the bot in any meaningful way. Any message from an unauthorized user is silently ignored or met with a non-informative response. Credentials that identify the bot and configure authorized users are never embedded in the codebase.

**Why this priority**: Security is foundational. Without access control, the bot could be exploited to run arbitrary operations on the host machine by any Telegram user. This must be in place before any other feature is exposed.

**Independent Test**: Can be tested by attempting to interact with the bot from an unauthorized Telegram account and verifying no session is started, no information is disclosed, and no error details are revealed. Independently verifiable without any coding session being run.

**Acceptance Scenarios**:

1. **Given** a Telegram user whose ID is not in the authorized list sends any message, **When** the bot receives the message, **Then** the bot does not process the request and does not reveal system information.
2. **Given** credentials are required to run the bot, **When** the bot starts, **Then** it reads all credentials from external secure configuration — no credentials are present in any source file.
3. **Given** an authorized user ID has been added to the configuration, **When** that user interacts with the bot, **Then** all bot features are available to them.

---

### Edge Cases

- What happens if OpenCode produces output faster than the messaging channel can deliver it? (Output buffering and rate limiting)
- What happens if the OpenCode session hangs indefinitely without producing output or prompts? → Addressed by FR-015: 30-minute inactivity timeout terminates the session and notifies the user.
- What happens if the provided directory path does not exist or the bot process lacks permission to access it?
- What happens if the OpenCode session crashes or is killed externally?
- What happens if the messaging service is temporarily unavailable while the session is active?
- What happens if the user sends input while no session is active?
- What happens if two messages arrive simultaneously while the bot is processing output from the session?
- What happens to a running session if the bot process restarts?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept task submissions from authorized users, specifying task type: work on an existing project (with local directory path) or create a new project (with target directory path).
- **FR-002**: System MUST validate that a provided directory path is accessible before starting a session; if invalid, it MUST return a clear error message without starting a session.
- **FR-003**: System MUST start an OpenCode session scoped to the directory specified in the task submission. Immediately after the subprocess starts, the system MUST write the task description as the first stdin line to prime OpenCode with the user's request.
- **FR-004**: System MUST forward all output, prompts, errors, and messages produced by the active OpenCode session to the authorized user.
- **FR-005**: System MUST accept user replies during an active session and pass them as input to the running OpenCode session.
- **FR-006**: System MUST notify the user when a session ends, including whether it completed successfully or with an error.
- **FR-007**: System MUST respond to status inquiry commands from authorized users with: the active task description, current session state (one of: IDLE, RUNNING, AWAITING INPUT, COMPLETED, FAILED), and recent session output.
- **FR-008**: When no session is active, status inquiries MUST indicate that no task is running.
- **FR-009**: System MUST restrict all interactions to a configurable set of authorized user identifiers.
- **FR-010**: System MUST load all credentials (including bot identity token and authorized user identifiers) from external secure configuration — nothing may be hardcoded in source files.
- **FR-011**: System MUST prevent a second session from starting while one is already active for a user, and MUST inform the user of the conflict with an option to cancel the active session.
- **FR-012**: System MUST handle unexpected session termination gracefully and notify the user.
- **FR-013**: All system components MUST have automated test coverage verifying correct behavior.
- **FR-014**: Unauthorized access attempts MUST be rejected without disclosing any system information, configuration, or error details to the requestor.
- **FR-015**: System MUST enforce a 30-minute inactivity timeout per session. If no output is received from the OpenCode subprocess within 30 minutes, the bot MUST notify the authorized user and terminate the session with FAILED state.
- **FR-016**: System MUST emit structured log entries (Python `logging`, stderr, INFO level) for: bot start/stop, session start/end, unauthorized access attempts, and unexpected errors (ERROR level with traceback).

### Non-Functional Requirements

- **NFR-001**: Message forwarding latency (session output → user notification) MUST not exceed 3 seconds under normal operating conditions.
- **NFR-002**: User reply latency (Telegram reply → session input delivered) MUST not exceed 3 seconds under normal operating conditions.
- **NFR-003**: The system MUST remain operational and responsive to status inquiries even while a session is actively producing high-volume output.
- **NFR-004**: See [constitution.md](../../.specify/memory/constitution.md) Principles I (Python Expertise) and IV (Code Quality). All code must conform to those standards and all functions/methods must include type annotations.
- **NFR-005**: Long output MUST be split into sequential ≤4096-character chunks (no truncation) to respect Telegram message size limits while preserving full output fidelity.
- **NFR-006**: The AWAITING_INPUT state is entered when the most-recently forwarded output line ends with a recognised prompt pattern (`?`, `> `, or `: `), enabling the bot to signal the user that input is expected.

### Key Entities

- **Task**: A coding request submitted by a user. Attributes: type (existing project / new project), directory path, and task description.
- **OpenCode Session**: A running instance of the OpenCode CLI tool scoped to a directory. Invoked as `opencode` with `cwd` set to the project directory; the task description is sent as the first stdin line immediately after start. Attributes: associated task, current state (IDLE / RUNNING / AWAITING_INPUT / COMPLETED / FAILED), recent output buffer, inactivity timer (30-minute timeout). AWAITING_INPUT is entered when the last forwarded output line ends with `?`, `> `, or `: `.
- **Authorized User**: A user whose identifier is present in the bot's secure configuration. Can submit tasks, receive session output, send replies, and query status.
- **Session Message**: A unit of communication flowing in either direction between an authorized user and an active OpenCode session.
- **Session Status**: A snapshot captured on demand: task description, current session state, and recent output.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An authorized user can successfully submit a task and receive a session-started confirmation within 5 seconds.
- **SC-002**: Output from the OpenCode session is delivered to the user within 3 seconds of being produced, under normal conditions. *(= NFR-001)*
- **SC-003**: A user reply sent via the messaging interface is received by the active session within 3 seconds of being sent. *(= NFR-002)*
- **SC-004**: Status inquiries return an accurate, current response within 3 seconds regardless of session activity level.
- **SC-005**: Unauthorized users receive no actionable information or confirmation of bot existence when attempting to interact, in 100% of interaction attempts.
- **SC-006**: All functional requirements have automated test cases that pass, demonstrating correct behavior for both success and failure paths.
- **SC-007**: The bot remains stable and responsive for sessions lasting at least 30 minutes of continuous activity without manual intervention.

## Assumptions

- The OpenCode CLI tool is already installed and runnable on the same machine where the bot process will run.
- Only one active OpenCode session per authorized user is supported at a time (concurrent multi-session management is out of scope for this version).
- The host machine has filesystem access to all local paths that authorized users may provide; path validation is limited to existence and accessibility checks.
- Very long session outputs that exceed the Telegram 4096-character message limit are split into sequential ≤4096-character chunks; no content is truncated.
- Session state is not persisted across bot process restarts; any running session is terminated if the bot stops.
- The bot is deployed and run by a developer or operator who manages the secure configuration; end-user self-registration is out of scope.
- Authorized user identifiers are maintained as a static list in configuration; dynamic addition/removal of authorized users at runtime is out of scope for this version.
- The host machine maintains stable connectivity to both the messaging platform and the local filesystem for the duration of sessions.
- Telegram API availability failures (network outages, rate limiting, gateway errors) are not handled at the application layer; network reliability and retry logic are infrastructure/ops concerns outside this feature's scope.
- Telegram's per-chat rate limit is respected via 1-second output buffering in `_dispatcher_task`. Sustained burst output may still approach API limits; this is an operational tuning concern outside this feature's scope.
- Latency SLOs (NFR-001, NFR-002, SC-004) and the 30-minute stability criterion (SC-007) are validated operationally via structured log timing and manual testing; automated performance or endurance regression tests are not in scope for this version.
