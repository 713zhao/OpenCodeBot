# Bot Command Contracts: Telegram OpenCode Bridge Bot

**Phase**: 1 — Design & Contracts  
**Branch**: `001-telegram-opencode-bridge`  
**Date**: 2026-05-01

This document defines the contract for every command and message type the bot exposes to authorized users. These contracts are the stable interface between the user and the bot; handler implementations must conform to them exactly.

---

## Commands

### `/start <task_description>` — Submit a Coding Task

**Trigger**: `/start` command with inline task description text.

**Full syntax**:
```
/start [existing|new] <path> <task description...>
```

**Parameters**:

| Position | Name | Required | Description |
|----------|------|----------|-------------|
| 1 | `task_type` | Yes | Must be exactly `existing` or `new` |
| 2 | `path` | Yes | Absolute or home-relative local filesystem path to the project directory |
| 3+ | `task_description` | Yes | Free-form task description (all remaining tokens) |

**Examples**:
```
/start existing /home/dev/myproject Fix the authentication bug in the login handler
/start new /home/dev/projects/new-api Build a REST API for user management
```

**Success response** (FR-001, FR-003, SC-001):
```
✅ Session started
Task: Fix the authentication bug in the login handler
Type: Existing project
Directory: /home/dev/myproject
```

> **Auto-prime (FR-003)**: The task description is written to OpenCode's stdin immediately after the subprocess starts — before this confirmation is sent. The user does **not** need to send a follow-up message to begin work; OpenCode is already primed and running when this reply arrives.

**Error responses**:

| Condition | Response |
|-----------|----------|
| Missing parameters | `Usage: /start [existing\|new] <path> <description>` |
| Invalid `task_type` | `Invalid task type. Use 'existing' or 'new'.` |
| Directory not found | `❌ Directory not found: /the/given/path` |
| Path is not a directory | `❌ Path is not a directory: /the/given/path` |
| Directory inaccessible | `❌ Directory is not accessible: /the/given/path` |
| Session already active | `⚠️ A session is already running. Send /cancel to stop it first, or wait for it to complete.` |

**Unauthorized user**: No response. Request silently discarded (FR-014).

---

### `/status` — Query Session Status

**Trigger**: `/status` command with no arguments.

**Success response — active session** (FR-007, SC-004):
```
📊 Session Status

State: RUNNING
Task: Fix the authentication bug in the login handler
Type: Existing project
Directory: /home/dev/myproject
Started: 2026-05-01 14:23:07 UTC

Recent output:
> Analyzing login handler...
> Found 3 potential issues
> Applying fix to auth.py...
```

**Success response — awaiting input** (FR-007):
```
📊 Session Status

State: AWAITING INPUT
Task: Fix the authentication bug in the login handler
...
Recent output:
> Should I also update the session expiry? [y/N]
```

**Success response — no active session** (FR-008):
```
💤 No active session. Use /start to begin a task.
```

**Unauthorized user**: No response. Request silently discarded (FR-014).

---

### `/cancel` — Cancel Active Session

**Trigger**: `/cancel` command with no arguments.

**Success response — session cancelled** (FR-006, FR-011):
```
🛑 Session cancelled.
Task: Fix the authentication bug in the login handler
Exit: terminated by user
```

**Response — no active session**:
```
ℹ️ No active session to cancel.
```

**Unauthorized user**: No response. Request silently discarded (FR-014).

---

### `/help` — Show Available Commands

**Trigger**: `/help` command with no arguments.

**Response**:
```
🤖 OpenCode Bridge Bot

Commands:
  /start [existing|new] <path> <description> — Start a coding session
  /status — Show current session status
  /cancel — Cancel the running session
  /help — Show this message
```

**Unauthorized user**: No response. Request silently discarded (FR-014).

---

## Message Input (Non-Command)

**Trigger**: Any non-command text message from an authorized user.

**Behaviour when session is RUNNING or AWAITING_INPUT** (FR-005):
- Text content is sent as a line to the active OpenCode session's stdin.
- No explicit acknowledgment reply; the session's response (if any) will appear as forwarded output.

**Behaviour when no session is active**:
```
ℹ️ No active session. Use /start to begin a task.
```

**Behaviour when session is COMPLETED or FAILED**:
```
ℹ️ Session has ended. Use /start to begin a new task.
```

**Unauthorized user**: No response. Request silently discarded (FR-014).

---

## Unsolicited Notifications (Bot → User)

These messages are proactively sent by the bot; they are not responses to commands.

### Session Output

Forwarded at most once per second (output buffering, R-004). Content is raw stdout/stderr lines from the OpenCode process, formatted in a monospace code block if the combined length ≤ 4096 chars.

```
[session output lines here]
```

If output exceeds 4096 chars in one buffer window, it is split across multiple messages, each within the limit.

### Session Completion Notification (FR-006)

Sent when the subprocess exits with code 0:
```
✅ Session completed successfully.
Task: Fix the authentication bug in the login handler
```

### Session Failure Notification (FR-006, FR-012)

Sent when the subprocess exits with a non-zero code or crashes:
```
❌ Session ended with an error.
Task: Fix the authentication bug in the login handler
Exit code: 1
```

### Session Timeout Notification (FR-015)

Sent when no stdout/stderr output is received from the subprocess for 30 consecutive minutes:
```
⏱️ Session timed out after 30 minutes of inactivity.
Task: Fix the authentication bug in the login handler
The session has been terminated.
```

The session state is set to FAILED before this message is sent. The user may start a new session with `/start`.

---

## Authorization Contract

All commands and message handlers MUST validate the requesting user's Telegram ID against the `authorized_user_ids` frozenset **before any processing**. Non-authorized requests:

1. **MUST NOT** trigger any session operation.
2. **MUST NOT** send any reply to the requesting user.
3. **MUST NOT** log the message content.
4. **MUST** log the unauthorized user ID and timestamp for audit purposes.

This contract is enforced by the `require_auth` decorator (see [research.md R-006](../research.md#r-006-authorization-middleware)).

---

## Input Constraints

| Input | Max length | Validation |
|-------|-----------|-----------|
| Task description | 2000 chars | Truncated to 2000 if longer; user notified |
| Directory path | OS path limit (4096 on Linux) | Validated via `Path.resolve()` + existence checks |
| Stdin reply to session | 4096 chars | Sent as-is; no length enforcement (user is authorized operator) |
