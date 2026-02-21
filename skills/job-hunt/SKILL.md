---
name: job-hunt
description: "Trigger the LinkedIn job-hunt workflow on demand and post results to Discord. Use when the user asks to: run the job hunt, find new jobs, scrape LinkedIn, check today's jobs, or anything related to automated job searching. Supports three modes: (1) scrape-only — preview new jobs without tailoring, (2) full run — scrape + tailor resumes + cover letters + PDFs + Discord report, (3) status — show today's output."
---

# Job Hunt Skill

Trigger the job-hunt workflow and post results to Discord.

**Before first use:** Edit the variables below to match your setup:
- `JOB_WORKFLOW_DIR` — absolute path to your cloned `job-workflow` folder
- `PYTHON` — path to the Python that has your dependencies installed (`which python3`)

```
JOB_WORKFLOW_DIR = ~/Projects/job-workflow
PYTHON           = python3
```

---

## Intent → Action mapping

| User says | Action |
|---|---|
| "有什么新职位" / "scrape jobs" / "preview jobs" | **scrape** |
| "跑一下求职" / "run job hunt" / "找工作" | **full run** |
| "今天跑了什么" / "job status" | **status** |

When intent is ambiguous, default to **scrape** (safe, fast, no Claude costs).

---

## Commands

### Scrape (preview only — ~3 min, no side effects)
```bash
cd {JOB_WORKFLOW_DIR} && {PYTHON} src/cli.py scrape
```
Outputs a JSON array of job objects. Parse and format for Discord.

### Full run (~12 min, tailors resumes + sends Discord report)
```bash
cd {JOB_WORKFLOW_DIR} && {PYTHON} src/cli.py run
```
Long-running — use `exec background=true yieldMs=30000`, poll until done.
The workflow itself sends the detailed Discord report automatically.

### Status
```bash
cd {JOB_WORKFLOW_DIR} && {PYTHON} src/cli.py status
```
Outputs JSON with today's companies and success/fail per job.

---

## How to handle each action

### Scrape
1. Run scrape command (foreground, ~3 min)
2. Parse JSON output
3. Post formatted message to Discord:
   ```
   🔍 **LinkedIn 今日新职位** — {date}
   Found {N} new job(s):

   1. **{title}** @ {company} | {location} | {age}
      🔗 {url}
      > {snippet}
   ```
4. If 0 jobs: post "今天暂时没有新职位，明天再看 👀"

### Full run
1. Tell user: "开始跑完整流水线，大概 10-12 分钟，完成后 Discord 会有报告 🚀"
2. Run in background (`exec background=true`)
3. When done: "✅ 完成！Discord job-hunt channel 里有完整报告"

### Status
1. Run status command
2. Parse JSON, post summary:
   ```
   📊 **今日求职状态** — {date}
   {total} 家公司 · ✅ {ok} 成功 · ❌ {failed} 失败
   ```

---

## Error handling
- **Scrape returns 0 jobs**: normal, LinkedIn may be slow — post friendly message
- **Exit code non-zero**: read last 20 lines of `{JOB_WORKFLOW_DIR}/logs/workflow.log`
- **Full run timeout (>15 min)**: post warning, check logs
