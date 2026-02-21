---
name: job-hunt
description: "Automated LinkedIn job-hunt assistant. Triggered by 'job search', 'job run', 'job status', 'job schedule', 'job add', 'job remove', 'job config', 'job tailor', 'job open', 'job reset' commands — or natural language equivalents like '找工作', '抓职位', '设定定时', '加关键词'. Use when the user wants to search jobs, run the full tailoring pipeline, check status, manage config, or schedule automation."
---

# Job Hunt Skill

**Workflow location:** `~/Projects/job-workflow-oss/`
**Python:** `/opt/homebrew/Caskroom/miniconda/base/bin/python3`
**CLI:** `~/Projects/job-workflow-oss/src/cli.py`
**Config:** `~/Projects/job-workflow-oss/config/search_config.json`

**Language rule:** Reply in Chinese if user writes Chinese, English if English. Mixed → Chinese.

---

## ⛔ CRITICAL RULES — Read Before Anything Else

1. **NEVER ask for LinkedIn credentials (email/password).** The scraper uses Playwright to scrape LinkedIn's PUBLIC search pages. No login required. No cookies. No credentials. Ever.
2. **NEVER create a separate project folder per user** (e.g. `~/Projects/job-workflow-lisa/`). All users share one project. User data is isolated in `config/users/{discord_id}/` only.
3. **NEVER ask users to DM credentials of any kind.** The only things you need from a user are: resume HTML file + name/email/bio text.
4. **NEVER invent setup steps** that aren't in this SKILL.md.

---

## Multi-User Support

Every command is **user-scoped**. Before running any command:

1. **Get the sender's Discord user ID** from message metadata (e.g. `970771448320897095`)
2. **Check if they're set up**:
   ```bash
   cd ~/Projects/job-workflow-oss && /opt/homebrew/Caskroom/miniconda/base/bin/python3 src/cli.py setup --user-id {SENDER_ID}
   ```
3. If `ready: false` → run **`job setup`** flow before anything else
4. Pass `--user-id {SENDER_ID}` to all `run`, `status`, `tailor` commands

Each user's data is isolated in `config/users/{discord_user_id}/`:
- `profile.json` — name, email, linkedin, bio
- `resume.html` — SDE resume
- `resume_ai.html` — AI/ML resume (optional)

---

## Quick Reference

| Command | Description |
|---|---|
| `job setup` | First-time setup — register resume + profile |
| `job search [Nd]` | Search jobs, list top 10 newest. Optional: `3d`, `7d`, `30d`... |
| `job run [Nd]` | Preview → confirm → tailor resumes + PDFs + Discord report |
| `job status` | Today's progress and output files |
| `job schedule HH:MM` | Set daily auto-run time |
| `job add <keyword>` | Add a keyword to SDE or AI search list |
| `job remove <keyword>` | Remove a keyword from search list |
| `job config` | Show current search config |
| `job tailor <url>` | Tailor resume for a single LinkedIn job URL |
| `job open` | Open today's output folder in Finder |
| `job reset` | Clear seen_jobs.json (reset dedup, search all again) |

---

## Time filter rule (applies to `job search` and `job run`)
- `Nd` = any number of days, e.g. `3d`, `7d`, `14d`, `30d`
- **With limit**: strictly filter jobs ≤ N days old. If 0 found → report 0, do NOT expand range.
- **Without limit**: return all available jobs sorted newest first.

To apply a time filter, temporarily patch `max_days_old` before scraping:
```bash
cd ~/Projects/job-workflow-oss && /opt/homebrew/Caskroom/miniconda/base/bin/python3 -c "
import json; p='config/search_config.json'
c=json.load(open(p)); c['max_days_old']={N}
json.dump(c,open(p,'w'),indent=2)
"
```
Restore to 0 after scrape completes (always, even on error).

---

## Command Details

### `job setup` (first-time onboarding)
Run when a new user's `ready: false`. Walk them through setup interactively.

> ⚠️ You only need TWO things: resume HTML + profile text. Do NOT ask for LinkedIn login, passwords, or any credentials.

1. Post:
   ```
   👋 还没有注册简历！需要以下两样东西：
   1️⃣ 发送你的简历 HTML 文件（直接上传到这个频道）
   2️⃣ 填写个人信息（姓名、邮箱、LinkedIn URL、个人简介）

   ⚠️ 不需要 LinkedIn 账号密码，不需要任何登录信息。
   ```
2. Wait for user to upload their resume HTML. Save the attachment content to:
   ```bash
   mkdir -p ~/Projects/job-workflow-oss/config/users/{SENDER_ID}
   # Save uploaded HTML to:
   ~/Projects/job-workflow-oss/config/users/{SENDER_ID}/resume.html
   ```
3. Ask for profile info (can be one message or separate):
   ```
   请提供：
   - 姓名
   - 邮箱
   - LinkedIn URL（可选）
   - 个人网站/Portfolio（可选）
   - 个人简介（2-6句，包括学历、工作经历、项目、技术栈）
   ```
4. Write `config/users/{SENDER_ID}/profile.json`:
   ```json
   {
     "name": "...",
     "email": "...",
     "linkedin": "...",
     "portfolio": "...",
     "resume_pdf_prefix": "{Name}-Resume",
     "bio": "..."
   }
   ```
5. Ask for their Discord notification webhook URL (optional):
   ```
   最后一步（可选）：请提供你的 Discord Webhook URL，用于把求职结果直接发到你的频道。
   在 Discord 频道设置 → 整合 → Webhooks → 新建 Webhook 里创建。
   没有的话直接跳过，会用全局默认 webhook。
   ```
   If provided, store in DB:
   ```bash
   cd ~/Projects/job-workflow-oss && /opt/homebrew/Caskroom/miniconda/base/bin/python3 -c "
   import sys; sys.path.insert(0, 'src')
   from dotenv import load_dotenv; load_dotenv('.env')
   import db
   db.upsert_user('{SENDER_ID}', notify_webhook_url='{WEBHOOK_URL}')
   print('OK')
   "
   ```
6. Save user to DB (upsert profile):
   ```bash
   cd ~/Projects/job-workflow-oss && /opt/homebrew/Caskroom/miniconda/base/bin/python3 -c "
   import sys, json; sys.path.insert(0, 'src')
   from dotenv import load_dotenv; load_dotenv('.env')
   import db
   profile = json.load(open('config/users/{SENDER_ID}/profile.json'))
   db.upsert_user('{SENDER_ID}', **profile)
   print('DB synced')
   "
   ```
7. Confirm: "✅ 注册完成！现在可以用 `job run` 开始投简历了 🚀"

---

### `job search [Nd]`
1. **Pre-run message** — post immediately before starting:
   ```
   🔍 正在搜索 LinkedIn 职位{（过去Nd）if filtered}，预计 2-3 分钟，结果直接发到这里...
   ```
2. Apply time filter if given
3. Run: `cd ~/Projects/job-workflow-oss && /opt/homebrew/Caskroom/miniconda/base/bin/python3 src/cli.py scrape`
4. Sort by `days_old` ascending (newest first), take top 10
5. Post to Discord:
```
🔍 **LinkedIn 职位搜索** — {date} {(过去Nd) if filtered}
找到 {N} 个职位，最新 10 个：

1. **{title}** @ {company} | {location} | 📅 {age}
   🔗 {url}
   > {snippet}
```
- 0 results + time limit: "过去 {N} 天内没有新职位，可用 `job search` 搜全部。"
- 0 results no limit: "暂时没有新职位，稍后再试 👀"

---

### `job run [Nd]`
**Step 1 — Pre-run message** (post immediately):
```
🚀 Job Run 启动{（过去Nd）if filtered else （无时间限制）}
📡 Step 1/3: 正在搜索 LinkedIn 职位，预计 2-3 分钟...
⚙️ 配置：SF + Remote | SDE 目标 10 个 · AI 目标 5 个 | 4 个并发
```

**Step 2 — Preview:** Run scrape (same as `job search`), then append:
```
📋 以上 10 个职位按最新排序。
回复 ✅ 确认开始定制简历，或告诉我要跳过哪些。
```

**Step 3 — Wait for confirmation:**
- ✅ / "确认" / "yes" / "go" → proceed
- "跳过 X, Y" → note, proceed
- "取消" / "cancel" → abort, post "已取消"

**Step 4 — Run (non-blocking):**
1. Post: "⚙️ Step 2/3: 开始定制简历 + Cover Letter，约 10-15 分钟，本地 Terminal 会弹出进度窗口，完成后 Discord 收到报告 📬"
2. Run launcher (returns immediately — does NOT block the session):
   ```bash
   bash ~/Projects/job-workflow-oss/run_local.sh run {SENDER_ID}
   ```
3. Immediately reply "✅ 已在后台启动！完成后推送报告到 Discord 📬" — do NOT wait or poll.

> **Important:** `run_local.sh` opens a macOS Terminal window AND runs the workflow as a detached nohup process. The workflow self-notifies Discord when done.

---

### `job status`
1. `cd ~/Projects/job-workflow-oss && /opt/homebrew/Caskroom/miniconda/base/bin/python3 src/cli.py status --user-id {SENDER_ID}`
2. Post:
```
📊 **今日求职状态** — {date}
{total} 家公司 · ✅ {ok} 成功 · ❌ {failed} 失败

✅ OpenAI — 简历 + PDF + Cover Letter + Why OpenAI
❌ Stripe — 仅 HTML（PDF 失败）
```
No output today → "今天还没跑过，用 `job run` 开始 🚀"

---

### `job schedule HH:MM`
1. Parse time (24h, e.g. `09:00` → hour=9, min=0)
2. Set cron:
```bash
(crontab -l 2>/dev/null | grep -v "job-workflow-oss/run.sh"; echo "{min} {hour} * * * /Users/zihanwang/Projects/job-workflow-oss/run.sh >> /Users/zihanwang/Projects/job-workflow-oss/logs/cron.log 2>&1") | crontab -
```
3. Verify: `crontab -l | grep job-workflow-oss`
4. Confirm: "⏰ 每天 {HH:MM} 自动跑，结果推送到 #job-hunt"

Cancel schedule: `(crontab -l 2>/dev/null | grep -v "job-workflow-oss/run.sh") | crontab -`

---

### `job add <keyword>`
1. Read `~/Projects/job-workflow-oss/config/search_config.json`
2. Ask if SDE or AI category (if unclear from keyword)
3. Append keyword to the appropriate category's `keywords` array
4. Write back, confirm: "✅ 已添加 '{keyword}' 到 {category} 搜索列表"

### `job remove <keyword>`
1. Read config, find and remove the keyword (case-insensitive match)
2. Write back, confirm: "✅ 已从搜索列表移除 '{keyword}'"
3. If not found: "未找到 '{keyword}'，用 `job config` 查看当前关键词"

### `job config`
1. Read `~/Projects/job-workflow-oss/config/search_config.json`
2. Post formatted summary (strip `_comment` keys):
```
⚙️ **当前求职配置**

📍 地区: San Francisco, CA · Remote
⏱ 时间限制: 无限制 (max_days_old=0)
⚡ 并发 workers: 4

🔎 SDE 关键词 (目标 {N} 个):
  Software Engineer, Full Stack Engineer, ...

🤖 AI 关键词 (目标 {N} 个):
  AI Engineer, ML Engineer, ...
```

### `job tailor <url>`
1. Tell user: "正在抓取 JD 并定制简历，大约 3-5 分钟..."
2. Scrape the JD from the URL using Playwright (reuse scraper logic)
3. Run tailor + cover letter for that single job
4. Report paths of generated files

Implementation:
```bash
cd ~/Projects/job-workflow-oss && /opt/homebrew/Caskroom/miniconda/base/bin/python3 -c "
import sys; sys.path.insert(0,'src'); sys.path.insert(0,'.')
from dotenv import load_dotenv; load_dotenv('.env')
from playwright.sync_api import sync_playwright
from resume_tailor import tailor_resume
from cover_letter import generate_cover_letter
from pdf_generator import html_to_pdf
from pathlib import Path
from datetime import date
import re, json

url = '{url}'
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    pg.goto(url, timeout=25000); pg.wait_for_timeout(3000)
    jd = ''
    for sel in ['.show-more-less-html__markup','#job-details','.description__text']:
        el = pg.query_selector(sel)
        if el: jd = el.inner_text().strip(); break
    title = (pg.query_selector('h1') or pg.query_selector('.topcard__title'))
    title = title.inner_text().strip() if title else 'Software Engineer'
    comp = pg.query_selector('.topcard__org-name-link')
    company = comp.inner_text().strip() if comp else 'Company'
    b.close()
job = {'job_id':'manual','title':title,'company':company,'location':'','url':url,'description':jd}
out = Path('resume/output') / date.today().isoformat() / re.sub(r'[^a-zA-Z0-9_-]','_',company)
out.mkdir(parents=True, exist_ok=True)
html = tailor_resume(job, out)
cl = generate_cover_letter(job, out)
pdf = html_to_pdf(html, f'Resume-{company}') if html else None
print(json.dumps({'html':str(html),'pdf':str(pdf),'cl':str(cl.get(\"cover_letter\")),'why':str(cl.get(\"why_company\"))}))
"
```

### `job open`
```bash
open ~/Projects/job-workflow-oss/resume/output/$(date +%Y-%m-%d) 2>/dev/null || open ~/Projects/job-workflow-oss/resume/output/
```
Confirm: "📁 已打开今天的输出文件夹"

### `job reset`
1. Confirm with user first: "⚠️ 这会清空已搜索记录，下次会重新搜所有职位。确认？"
2. On confirm:
```bash
echo '{"seen_ids":[],"last_updated":null}' > ~/Projects/job-workflow-oss/data/seen_jobs.json
```
3. Confirm: "✅ 已重置，下次搜索将从头开始"

---

## Error handling
- **Scrape fails / 0 jobs**: friendly message, suggest retry
- **Non-zero exit**: read last 20 lines of `~/Projects/job-workflow-oss/logs/workflow.log`
- **Run timeout >20 min**: post warning with log tail
- **Schedule parse error**: ask user for HH:MM format
- **keyword not found in remove**: show current list
