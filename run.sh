#!/bin/bash
# Daily job-hunt workflow runner
# Cron: 30 7 * * * /Users/zihanwang/Projects/job-workflow/run.sh >> /Users/zihanwang/Projects/job-workflow/logs/cron.log 2>&1

export PATH="/Users/zihanwang/.local/bin:/opt/homebrew/Caskroom/miniconda/base/bin:/usr/local/bin:/usr/bin:/bin"
export HOME="/Users/zihanwang"
DIR="/Users/zihanwang/Projects/job-workflow"

cd "$DIR"

# Load .env
set -a; [ -f "$DIR/.env" ] && source "$DIR/.env"; set +a

# ── Pre-flight: check Claude CLI auth ──────────────────────────────────────
CLAUDE_BIN="$(which claude 2>/dev/null || echo /Users/zihanwang/.local/bin/claude)"
AUTH_OK=false

if [ -x "$CLAUDE_BIN" ]; then
    TEST=$(echo "ping" | "$CLAUDE_BIN" --print "reply with: ok" 2>&1)
    if echo "$TEST" | grep -qi "ok"; then
        AUTH_OK=true
    fi
fi

if [ "$AUTH_OK" = false ]; then
    echo "[$(date '+%H:%M:%S')] ❌ Claude CLI not authenticated — aborting run"

    # Send Discord alert
    if [ -n "$DISCORD_WEBHOOK_URL" ]; then
        curl -s -X POST "$DISCORD_WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"content\": \"⚠️ **求职自动化失败** — Claude CLI 登录过期！\n请在终端运行 \`claude login\` 重新登录，然后手动触发 \`job run\`。\"}"
    fi
    exit 1
fi

echo "[$(date '+%H:%M:%S')] ✅ Claude CLI auth OK — starting workflow"

# ── Run main pipeline ──────────────────────────────────────────────────────
/opt/homebrew/Caskroom/miniconda/base/bin/python3 src/main.py
