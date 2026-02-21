#!/usr/bin/env bash
# run_local.sh — Launch the job-hunt workflow in a new Terminal window.
# Called by OpenClaw SKILL; returns immediately so the agent stays responsive.
#
# Usage:
#   bash run_local.sh          → full run
#   bash run_local.sh scrape   → scrape only
#   bash run_local.sh status   → today's status
#
# What it does:
#   1. Opens a new macOS Terminal window showing live output (tail -F)
#   2. Starts the workflow as a detached nohup process (survives Terminal close)
#   3. Saves all output to logs/current_run.log

set -euo pipefail

PROJ_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="/opt/homebrew/Caskroom/miniconda/base/bin/python3"
CMD="${1:-run}"
USER_ID="${2:-}"   # Discord user ID, e.g. 970771448320897095
LOG_FILE="${PROJ_DIR}/logs/current_run${USER_ID:+_$USER_ID}.log"
PID_FILE="${PROJ_DIR}/logs/run${USER_ID:+_$USER_ID}.pid"

mkdir -p "${PROJ_DIR}/logs"

# ── Kill any previous run ─────────────────────────────────────────────────────
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[run_local] Killing previous run (pid=$OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$PID_FILE"
fi

# Rotate log
[[ -f "$LOG_FILE" ]] && mv "$LOG_FILE" "${LOG_FILE}.prev" 2>/dev/null || true

# ── Launch detached subprocess (survives Terminal close) ──────────────────────
EXTRA_ARGS=""
[ -n "$USER_ID" ] && EXTRA_ARGS="--user-id $USER_ID"

# shellcheck disable=SC2086
nohup "$PYTHON" -u "${PROJ_DIR}/src/cli.py" "$CMD" $EXTRA_ARGS \
    >> "$LOG_FILE" 2>&1 &
BGPID=$!
echo "$BGPID" > "$PID_FILE"
echo "$(date '+%Y-%m-%d %H:%M:%S')  [run_local] Started pid=$BGPID cmd=$CMD" | tee -a "$LOG_FILE"

# ── Open Terminal window to watch the log ────────────────────────────────────
osascript - "$LOG_FILE" "$CMD" <<'APPLESCRIPT'
on run argv
    set logFile to item 1 of argv
    set cmdLabel to item 2 of argv
    tell application "Terminal"
        activate
        -- Try to reuse an existing "Job Hunt" window; else open new
        set jobWins to (every window whose name contains "Job Hunt")
        if (count of jobWins) > 0 then
            set w to item 1 of jobWins
            set selected tab of w to first tab of w
        else
            do script ""
            set w to front window
        end if
        set t to first tab of w
        -- Clear and tail the log
        do script "clear && echo '🤖 Job Hunt — " & cmdLabel & "  (Ctrl-C safe — process keeps running)' && echo '' && tail -F '" & logFile & "'" in t
        set custom title of t to "🤖 Job Hunt — " & cmdLabel
    end tell
end run
APPLESCRIPT

echo "[run_local] Terminal window opened. Job running detached as pid=$BGPID"
