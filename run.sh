#!/bin/bash
# Daily job-hunt workflow runner
# Cron example:
#   0 9 * * * cd $HOME/Projects/job-workflow-oss && bash run.sh >> logs/cron.log 2>&1

# Update PATH for cron environment (add your tool paths here)
export PATH="$HOME/.local/bin:/opt/homebrew/Caskroom/miniconda/base/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Load .env
set -a; [ -f "$DIR/.env" ] && source "$DIR/.env"; set +a

# ── Resolve Python & Claude ────────────────────────────────────────────────
PYTHON_BIN="${PYTHON_BIN:-$(which python3)}"
CLAUDE_BIN="${CLAUDE_BIN:-$(which claude 2>/dev/null || echo claude)}"

# ── Pre-flight: check Claude CLI auth (only when LLM_MODE=claude) ─────────
if [ "${LLM_MODE:-claude}" = "claude" ]; then
    AUTH_OK=false
    if [ -x "$CLAUDE_BIN" ]; then
        TEST=$(echo "ping" | "$CLAUDE_BIN" --print "reply with: ok" 2>&1)
        if echo "$TEST" | grep -qi "ok"; then
            AUTH_OK=true
        fi
    fi

    if [ "$AUTH_OK" = false ]; then
        echo "[$(date '+%H:%M:%S')] ❌ Claude CLI not authenticated — aborting run"
        if [ -n "$DISCORD_WEBHOOK_URL" ]; then
            curl -s -X POST "$DISCORD_WEBHOOK_URL" \
                -H "Content-Type: application/json" \
                -d "{\"content\": \"⚠️ **Job Hunt Failed** — Claude CLI auth expired! Run \`claude login\` to fix.\"}"
        fi
        exit 1
    fi
    echo "[$(date '+%H:%M:%S')] ✅ Claude CLI auth OK — starting workflow"
fi

# ── Run main pipeline ──────────────────────────────────────────────────────
"$PYTHON_BIN" src/main.py
