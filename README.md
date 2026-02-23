# 🔍 LinkedIn Job-Hunt Workflow

Automated daily pipeline:
1. **Scrape LinkedIn** for entry-level SDE / AI Engineer roles (configurable)
2. **Tailor the HTML resume** to each JD using an LLM (Claude / Codex)
3. **Generate a PDF** from the tailored HTML via Playwright
4. **Notify via Discord** with a job summary
5. **Log to Notion** — each job added to your tracker as "Not started"

---

## Setup

### 1. Clone & install dependencies
```bash
git clone https://github.com/ziw224/linkedin-job-workflow.git
cd linkedin-job-workflow
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure credentials
```bash
cp .env.example .env
# Fill in .env — see .env.example for all required vars
```

### 3. Add your candidate profile
```bash
cp config/candidate.txt.example config/candidate.txt
# Edit config/candidate.txt with your real background
# This file is gitignored — your personal info stays local
```

### 4. Add your base resume
Put your resume HTML at `resume/base_resume.html` (see `resume/` for the expected format).

### 5. Run manually
```bash
python src/main.py
```

Tailored resumes appear in `resume/output/YYYY-MM-DD/{Company}/`.

### 6. Set up daily cron (9 AM)
```bash
crontab -e
```
Add:
```
0 9 * * * cd $HOME/Projects/linkedin-job-workflow && bash run.sh >> logs/cron.log 2>&1
```

---

## Project Structure

```
├── src/
│   ├── main.py                 # Orchestrator
│   ├── linkedin_scraper.py     # LinkedIn search via Playwright
│   ├── resume_tailor.py        # LLM-powered resume tailoring
│   ├── cover_letter.py         # Cover letter + "Why Company" generation
│   ├── pdf_generator.py        # HTML → PDF via Playwright
│   ├── notifier.py             # Discord webhook notifications
│   └── notion_tracker.py       # Notion DB integration
├── config/
│   ├── search_config.json      # Keywords, locations, targets
│   ├── candidate.txt           # Your background (gitignored)
│   └── candidate.txt.example   # Template
├── resume/
│   ├── base_resume.html        # Master resume (edit this)
│   └── output/                 # Tailored resumes per job (gitignored)
├── data/
│   └── seen_jobs.json          # Dedup tracker (gitignored)
├── logs/                       # Run logs (gitignored)
├── .env                        # Your secrets (gitignored)
├── .env.example                # Template
└── requirements.txt
```

---

## Customizing Search

Edit `config/search_config.json`:
```json
{
  "locations": ["San Francisco, CA", "Remote"],
  "categories": {
    "sde": { "keywords": ["Software Engineer", "Full Stack Engineer"], "target_count": 6 },
    "ai":  { "keywords": ["AI Engineer", "Applied AI Engineer"],       "target_count": 4 }
  }
}
```

---

## LLM Backends

Set `LLM_MODE` in `.env`:
- `claude` — Claude CLI (Max subscription, no API billing)
- `codex` — OpenAI Codex CLI
- `openclaw` — OpenClaw local agent

---

## Notes

- `seen_jobs.json` ensures each job is processed only once. Reset with:
  ```bash
  echo '{"seen_ids": []}' > data/seen_jobs.json
  ```
- Claude tailors resumes with minimal edits — it will **never fabricate** experience.
- Notion integration requires a Notion Internal Integration token + DB ID in `.env`.
