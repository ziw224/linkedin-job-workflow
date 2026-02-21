---
name: job-hunt
description: "Automated LinkedIn job-hunt assistant. Triggered by 'job search', 'job run', 'job status', 'job schedule', 'job add', 'job remove', 'job config', 'job tailor', 'job open', 'job reset' commands — or natural language equivalents like '找工作', '抓职位', '设定定时', '加关键词'. Use when the user wants to search jobs, run the full tailoring pipeline, check status, manage config, or schedule automation."
---

# Job Hunt Skill

**Workflow location:** `~/Projects/job-workflow/`
**Python:** `/opt/homebrew/Caskroom/miniconda/base/bin/python3`
**CLI:** `~/Projects/job-workflow/src/cli.py`
**Config:** `~/Projects/job-workflow/config/search_config.json`

**Language rule:** Reply in Chinese if user writes Chinese, English if English. Mixed → Chinese.

---

## Quick Reference

| Command | Description |
|---|---|
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
cd ~/Projects/job-workflow && /opt/homebrew/Caskroom/miniconda/base/bin/python3 -c "
import json; p='config/search_config.json'
c=json.load(open(p)); c['max_days_old']={N}
json.dump(c,open(p,'w'),indent=2)
"
```
Restore to 0 after scrape completes (always, even on error).

---

## Command Details

### `job search [Nd]`
1. **Pre-run message** — post immediately before starting:
   ```
   🔍 正在搜索 LinkedIn 职位{（过去Nd）if filtered}，预计 2-3 分钟，结果直接发到这里...
   ```
2. Apply time filter if given
3. Run: `cd ~/Projects/job-workflow && /opt/homebrew/Caskroom/miniconda/base/bin/python3 src/cli.py scrape`
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

**Step 4 — Run:**
1. Post: "⚙️ Step 2/3: 开始定制简历 + Cover Letter，约 10-15 分钟，完成后 #job-hunt 收到完整报告 📬"
2. `cd ~/Projects/job-workflow && /opt/homebrew/Caskroom/miniconda/base/bin/python3 src/cli.py run` (background, poll every 60s)
3. Done: "✅ Step 3/3: 完成！共处理 {N} 家公司，去 #job-hunt 查看 📬"

---

### `job status`
1. `cd ~/Projects/job-workflow && /opt/homebrew/Caskroom/miniconda/base/bin/python3 src/cli.py status`
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
(crontab -l 2>/dev/null | grep -v "job-workflow/run.sh"; echo "{min} {hour} * * * /Users/zihanwang/Projects/job-workflow/run.sh >> /Users/zihanwang/Projects/job-workflow/logs/cron.log 2>&1") | crontab -
```
3. Verify: `crontab -l | grep job-workflow`
4. Confirm: "⏰ 每天 {HH:MM} 自动跑，结果推送到 #job-hunt"

Cancel schedule: `(crontab -l 2>/dev/null | grep -v "job-workflow/run.sh") | crontab -`

---

### `job add <keyword>`
1. Read `config/search_config.json`
2. Ask if SDE or AI category (if unclear from keyword)
3. Append keyword to the appropriate category's `keywords` array
4. Write back, confirm: "✅ 已添加 '{keyword}' 到 {category} 搜索列表"

### `job remove <keyword>`
1. Read config, find and remove the keyword (case-insensitive match)
2. Write back, confirm: "✅ 已从搜索列表移除 '{keyword}'"
3. If not found: "未找到 '{keyword}'，用 `job config` 查看当前关键词"

### `job config`
1. Read `config/search_config.json`
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
cd ~/Projects/job-workflow && /opt/homebrew/Caskroom/miniconda/base/bin/python3 -c "
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
# scrape JD
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
pdf = html_to_pdf(html, f'{Your Name}-Resume-{company}') if html else None
print(json.dumps({'html':str(html),'pdf':str(pdf),'cl':str(cl.get(\"cover_letter\")),'why':str(cl.get(\"why_company\"))}))
"
```

### `job open`
```bash
open ~/Projects/job-workflow/resume/output/$(date +%Y-%m-%d) 2>/dev/null || open ~/Projects/job-workflow/resume/output/
```
Confirm: "📁 已打开今天的输出文件夹"

### `job reset`
1. Confirm with user first: "⚠️ 这会清空已搜索记录，下次会重新搜所有职位。确认？"
2. On confirm:
```bash
echo '{"seen_ids":[],"last_updated":null}' > ~/Projects/job-workflow/data/seen_jobs.json
```
3. Confirm: "✅ 已重置，下次搜索将从头开始"

---

## Error handling
- **Scrape fails / 0 jobs**: friendly message, suggest retry
- **Non-zero exit**: read last 20 lines of `~/Projects/job-workflow/logs/workflow.log`
- **Run timeout >20 min**: post warning with log tail
- **Schedule parse error**: ask user for HH:MM format
- **keyword not found in remove**: show current list
