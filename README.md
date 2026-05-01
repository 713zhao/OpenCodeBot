# Telegram OpenCode Bridge Bot

An async Python service that bridges authorized Telegram users to live [OpenCode](https://opencode.ai) CLI sessions running on the host machine.

## Prerequisites

- Python 3.13.5 (recommended; 3.11+ minimum)
- `opencode` CLI installed and on `PATH`
- A Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- Your Telegram user ID (e.g., from [@userinfobot](https://t.me/userinfobot))

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env
# Edit .env and fill in TELEGRAM_BOT_TOKEN and AUTHORIZED_USER_IDS
```

## Running

```bash
python -m telegram_opencode.main
```

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start [existing\|new] <path> <description>` | Start a coding session |
| `/status` | Show current session state and recent output |
| `/cancel` | Cancel the running session |
| `/help` | Show command listing |

Plain text messages are relayed as stdin to the active session.

## Development

```bash
# Run tests
pytest

# Lint
ruff check src/ tests/

# Type check
mypy --strict src/
```

## Security

Only users in `AUTHORIZED_USER_IDS` (comma-separated env var) can interact with the bot.  
The `.env` file must never be committed to version control — it is listed in `.gitignore`.
