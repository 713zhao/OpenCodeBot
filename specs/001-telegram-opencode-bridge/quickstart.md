# Quickstart: Telegram OpenCode Bridge Bot

**Branch**: `001-telegram-opencode-bridge`  
**Date**: 2026-05-01

---

## Prerequisites

- Python 3.11 or later (`python --version`)
- `opencode` CLI installed and on `PATH` (`opencode --version`)
- A Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- Your Telegram user ID (send any message to [@userinfobot](https://t.me/userinfobot))

---

## Setup

### 1. Clone and install

```bash
git clone <repo-url>
cd opencoding
pip install -e ".[dev]"
```

The `[dev]` extras include `pytest`, `pytest-asyncio`, `ruff`, `black`, and `mypy`.

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```dotenv
TELEGRAM_BOT_TOKEN=123456789:AABBCCDDEEFFaabbccddeeff...
AUTHORIZED_USER_IDS=123456789,987654321
```

> **Security**: `.env` is listed in `.gitignore` and must never be committed to version control.

### 3. Run the bot

```bash
python -m telegram_opencode.main
```

You should see:
```
INFO  Starting Telegram OpenCode Bridge Bot...
INFO  Authorized users: 2 configured
INFO  Bot polling started.
```

---

## Using the Bot

### Start a session on an existing project

```
/start existing /home/dev/myproject Fix the login bug in auth.py
```

### Start a session to create a new project

```
/start new /home/dev/projects/todo-api Build a simple REST API for a to-do list
```

### Check session status

```
/status
```

### Reply to an OpenCode prompt

Just send a plain message (no command prefix):

```
y
```

### Cancel a running session

```
/cancel
```

---

## Development

### Run tests

```bash
pytest
```

### Run tests with coverage

```bash
pytest --cov=telegram_opencode --cov-report=term-missing
```

Coverage must meet the ≥ 80% line coverage threshold set in `pyproject.toml`.

### Lint and format

```bash
ruff check src/ tests/
black --check src/ tests/
```

### Type-check

```bash
mypy src/
```

---

## Project Layout

```
src/telegram_opencode/
├── main.py       # Entry point
├── bot.py        # Telegram handlers + require_auth decorator
├── session.py    # OpenCodeSession, SessionState, Task, SessionStatus
└── config.py     # Config dataclass (loaded from .env)

tests/
├── test_bot.py
├── test_session.py
└── test_config.py

pyproject.toml    # All tool configuration
.env.example      # Environment variable template
```

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | Bot API token from BotFather |
| `AUTHORIZED_USER_IDS` | Yes | Comma-separated list of integer Telegram user IDs |

---

## Common Issues

**Bot doesn't respond to commands**  
Check that your Telegram user ID is in `AUTHORIZED_USER_IDS`. Unauthorized users receive no response by design.

**`opencode` command not found**  
Ensure `opencode` is installed and on your `PATH`. Test with `opencode --version` in a terminal.

**Session hangs with no output**  
The OpenCode CLI may be waiting for input. Check `/status` for recent output, then send a reply to unblock it.
