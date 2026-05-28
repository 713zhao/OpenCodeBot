#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/opencodebot.log"
PID_FILE="$SCRIPT_DIR/opencodebot.pid"

if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "OpenCodeBot is already running (PID $PID)"
        exit 0
    else
        rm -f "$PID_FILE"
    fi
fi

cd "$SCRIPT_DIR"

# Activate virtual environment if it exists
if [[ -f "$SCRIPT_DIR/venv/bin/activate" ]]; then
    source "$SCRIPT_DIR/venv/bin/activate"
elif [[ -f "$SCRIPT_DIR/.venv/bin/activate" ]]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
fi

nohup python -m telegram_opencode.main >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "OpenCodeBot started (PID $(cat "$PID_FILE")). Logs: $LOG_FILE"
