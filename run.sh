#!/bin/bash
# Daily job-hunt workflow runner
# Cron example (7:30 AM daily):
#   30 7 * * * /path/to/job-workflow/run.sh >> /path/to/job-workflow/logs/cron.log 2>&1

# Change to the directory this script lives in
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Add common Python/tool locations to PATH
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/opt/homebrew/Caskroom/miniconda/base/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# Run the workflow
python3 src/main.py
