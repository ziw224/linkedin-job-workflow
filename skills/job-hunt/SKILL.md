---
name: job-hunt
description: "Automated LinkedIn job-hunt assistant. Triggered by /search, /run, /status, /schedule commands — or natural language equivalents like '找工作', '抓职位', '看今天进度', '设定定时'. Use when the user wants to search jobs, run the full tailoring pipeline, check application status, or schedule daily automation."
---

# Job Hunt Skill

**Workflow location:** `~/Projects/job-workflow/`
**Python:** `/opt/homebrew/Caskroom/miniconda/base/bin/python3`
**CLI:** `~/Projects/job-workflow/src/cli.py`

**Language rule:** Detect the user's language from their message. Reply in Chinese if they write Chinese, English if English. Mixed input → use Chinese.

---

## Commands

### `/search [Nd]`
Search LinkedIn for jobs and list results. No tailoring, no side effects.

Optional time filter: `/search 7d` = last 7 days only, `/search` = no limit.

**Time filter logic (strict — no fallback):**
- With limit (e.g. `7d`): only return jobs ≤ 7 days old. If 0 found, report 0 — do NOT expand the range.
- Without limit: return all available jobs, sorted newest first.

**Steps:**
1. Before running, check if a time filter was given. If yes, temporarily update `max_days_old` in `config/search_config.json`:
   ```bash
   # e.g. for /search 7d:
   cd ~/Projects/job-workflow && python3 -c "
   import json; p='config/search_config.json'
   c=json.load(open(p)); c['max_days_old']=7
   json.dump(c,open(p,'w'),indent=2)
   "
   ```
   Restore to 0 after scrape completes.
2. Run: `cd ~/Projects/job-workflow && /opt/homebrew/Caskroom/miniconda/base/bin/python3 src/cli.py scrape`
3. Parse JSON output. Sort by `days_old` ascending (newest first). Take top 10.
4. Post formatted list to Discord (current channel):

```
🔍 **LinkedIn 职位搜索结果** — {date}{time_filter_note}
共找到 {N} 个职位，以下是最新的 10 个：

1. **{title}** @ {company} | {location} | 📅 {age}
   🔗 {url}
   > {snippet}
```

If 0 results with time limit: "过去 {N} 天内没有找到新职位。可以用 `/search` 搜索全部范围。"
If 0 results no limit: "暂时没有找到新职位，稍后再试 👀"

---

### `/run [Nd]`
Full pipeline with user confirmation before processing. Supports same time filter as `/search` (e.g. `/run 7d` = last 7 days only, strict — no fallback expansion).

**Steps:**

**Step 1 — Preview:**
1. Apply time filter if given (same strict logic as /search — no fallback)
2. Run scrape command, sort newest first, take top 10
3. Post the job list to Discord with a confirmation prompt at the end:
   ```
   📋 以上是今日精选的 10 个职位，按最新排序。
   回复 ✅ 确认开始定制简历，或告诉我要跳过哪些。
   ```

**Step 2 — Wait for confirmation:**
- User replies ✅ / "确认" / "yes" / "go" → proceed
- User says "跳过 X, Y" → note which to skip, then proceed
- User says "取消" / "cancel" → abort, post "已取消 ✅"

**Step 3 — Run full pipeline:**
1. Tell user: "🚀 开始定制简历，大约需要 10-15 分钟，完成后 Discord 会收到详细报告。"
2. Run: `cd ~/Projects/job-workflow && /opt/homebrew/Caskroom/miniconda/base/bin/python3 src/cli.py run`
   - Use `exec background=true`, poll every 60s
3. When done: "✅ 完成！去 #job-hunt 查看今天的简历报告 📬"

---

### `/status`
Check today's progress and output files.

**Steps:**
1. Run: `cd ~/Projects/job-workflow && /opt/homebrew/Caskroom/miniconda/base/bin/python3 src/cli.py status`
2. Parse JSON. Post summary:

```
📊 **今日求职状态** — {date}
处理了 {total} 家公司 · ✅ {ok} 成功 · ❌ {failed} 失败

✅ Notion — 简历 + PDF + Cover Letter + Why Notion
✅ OpenAI — 简历 + PDF + Cover Letter + Why OpenAI
❌ Stripe — 仅 HTML（PDF 生成失败）
```

If no output today: "今天还没有跑过流水线。发 /run 开始 🚀"

---

### `/schedule HH:MM`
Set a daily cron job to auto-run the full pipeline.

**Steps:**
1. Parse the time (24h format, e.g. `/schedule 09:00` → hour=9, min=0)
2. Run:
```bash
(crontab -l 2>/dev/null | grep -v "job-workflow/run.sh"; echo "{min} {hour} * * * /Users/zihanwang/Projects/job-workflow/run.sh >> /Users/zihanwang/Projects/job-workflow/logs/cron.log 2>&1") | crontab -
```
3. Verify: `crontab -l | grep job-workflow`
4. Post confirmation:
```
⏰ 已设定每天 {HH:MM} 自动运行求职流水线
完成后结果会自动推送到 Discord #job-hunt
```

To cancel schedule: user says "取消定时" → remove the line:
```bash
(crontab -l 2>/dev/null | grep -v "job-workflow/run.sh") | crontab -
```

---

## Error handling
- **Scrape fails / 0 jobs**: post friendly message, suggest retry
- **cli.py exits non-zero**: read `~/Projects/job-workflow/logs/workflow.log` last 20 lines
- **Full run timeout >20 min**: post warning with log tail
- **Schedule parse error**: ask user to re-enter in HH:MM format
