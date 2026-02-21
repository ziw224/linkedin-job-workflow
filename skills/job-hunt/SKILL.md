---
name: job-hunt
description: "Automated LinkedIn job-hunt assistant. Triggered by /search, /run, /status, /schedule commands — or natural language equivalents like '找工作', '抓职位', '看今天进度', '设定定时'. Use when the user wants to search jobs, run the full tailoring pipeline, check application status, or schedule daily automation."
---

# Job Hunt Skill

**Setup variables (edit these after install):**
```
JOB_WORKFLOW_DIR = ~/Projects/job-workflow   ← your local path
PYTHON           = python3                   ← check with: which python3
```

**Language rule:** Detect the user's language from their message. Reply in Chinese if they write Chinese, English if English. Mixed input → use Chinese.

---

## Commands

### `/search`
Search LinkedIn for jobs and list results. No tailoring, no side effects.

**Steps:**
1. Run: `cd {JOB_WORKFLOW_DIR} && {PYTHON} src/cli.py scrape`
2. Parse JSON output. Sort by `days_old` ascending (newest first). Take top 10.
3. Post formatted list to Discord:

```
🔍 **LinkedIn Job Search** — {date}
Found {N} jobs. Here are the latest 10:

1. **{title}** @ {company} | {location} | 📅 {age}
   🔗 {url}
   > {snippet}
```

If 0 results: post "No new jobs found right now. Try again later 👀"

---

### `/run`
Full pipeline with user confirmation before processing.

**Step 1 — Preview:**
1. Run scrape, sort newest first, take top 10
2. Post job list + confirmation prompt:
   ```
   📋 Here are today's top 10 jobs, sorted by date.
   Reply ✅ to confirm and start tailoring, or tell me which ones to skip.
   ```

**Step 2 — Wait for confirmation:**
- User replies ✅ / "yes" / "go" / "确认" → proceed
- User says "skip X, Y" → note, proceed
- User says "cancel" / "取消" → abort

**Step 3 — Run full pipeline:**
1. Tell user: "🚀 Starting pipeline, ~10-15 min. Discord report when done."
2. Run: `cd {JOB_WORKFLOW_DIR} && {PYTHON} src/cli.py run` (background, poll every 60s)
3. When done: "✅ Done! Check #job-hunt for today's resume report 📬"

---

### `/status`
Check today's progress and output files.

**Steps:**
1. Run: `cd {JOB_WORKFLOW_DIR} && {PYTHON} src/cli.py status`
2. Parse JSON, post summary:
```
📊 **Job Hunt Status** — {date}
{total} companies · ✅ {ok} success · ❌ {failed} failed

✅ Notion — resume + PDF + cover letter + why-company
❌ Stripe — HTML only (PDF failed)
```

If no output today: "Nothing run yet today. Use /run to start 🚀"

---

### `/schedule HH:MM`
Set a daily cron job to auto-run the full pipeline.

**Steps:**
1. Parse time (24h format, e.g. `/schedule 09:00`)
2. Run:
```bash
(crontab -l 2>/dev/null | grep -v "job-workflow/run.sh"; echo "{MIN} {HOUR} * * * {JOB_WORKFLOW_DIR}/run.sh >> {JOB_WORKFLOW_DIR}/logs/cron.log 2>&1") | crontab -
```
3. Verify with `crontab -l | grep job-workflow`
4. Confirm to user: "⏰ Scheduled daily run at {HH:MM}. Results will post to Discord #job-hunt."

To cancel: `(crontab -l 2>/dev/null | grep -v "job-workflow/run.sh") | crontab -`

---

## Error handling
- **0 jobs found**: friendly message, suggest retry
- **Non-zero exit**: read last 20 lines of `{JOB_WORKFLOW_DIR}/logs/workflow.log`
- **Run timeout >20 min**: post warning with log tail
- **Schedule parse error**: ask user to re-enter in HH:MM format
