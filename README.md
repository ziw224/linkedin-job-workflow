# 🔍 LinkedIn Job-Hunt Workflow

Automated daily pipeline:
1. **Search LinkedIn** for entry-level Software/Full-Stack Engineer roles in SF & Remote
2. **Tailor the HTML resume** to each JD using Claude AI
3. **Generate a PDF** from the tailored HTML
4. **Notify via Discord** with a job summary

---

## Setup

### 1. Install dependencies
```bash
cd ~/Projects/job-workflow
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure credentials
```bash
cp .env.example .env
# Edit .env and fill in:
#   LINKEDIN_EMAIL    – your LinkedIn email
#   LINKEDIN_PASSWORD – your LinkedIn password
#   ANTHROPIC_API_KEY – from console.anthropic.com
```

### 3. Run manually
```bash
cd ~/Projects/job-workflow
python src/main.py
```

Tailored resumes appear in `resume/output/` as both `.html` and `.pdf`.

### 4. Set up daily cron (9 AM)
```bash
crontab -e
```
Add this line (adjust python path with `which python3`):
```
0 9 * * * cd /Users/zihanwang/Projects/job-workflow && /usr/bin/python3 src/main.py >> logs/workflow.log 2>&1
```

---

## Project Structure

```
job-workflow/
├── resume/
│   ├── base_resume.html        # Master resume (HTML, edit this)
│   └── output/                 # Tailored resumes per job
│       ├── 1234_Stripe_SWE.html
│       └── 1234_Stripe_SWE.pdf
├── src/
│   ├── main.py                 # Orchestrator
│   ├── linkedin_scraper.py     # Job search (API + Playwright fallback)
│   ├── resume_tailor.py        # Claude-powered resume tailoring
│   ├── pdf_generator.py        # HTML → PDF via Playwright
│   └── notifier.py             # Discord notification
├── config/
│   └── settings.py             # Keywords, locations, limits
├── data/
│   └── seen_jobs.json          # Dedup tracker
├── logs/
│   └── workflow.log            # Run logs
├── .env                        # Your secrets (gitignored)
├── .env.example
└── requirements.txt
```

---

## Customizing

**Change job keywords** → edit `config/settings.py`:
```python
SEARCH_KEYWORDS = ["Software Engineer", "Full Stack Engineer", ...]
SEARCH_LOCATIONS = ["San Francisco, CA", "Remote"]
```

**Update base resume** → edit `resume/base_resume.html`

**Change daily limit** → `MAX_JOBS_PER_RUN = 20` in `config/settings.py`

---

## Notes

- LinkedIn unofficial API (`linkedin-api`) may occasionally hit rate limits – the scraper adds polite delays automatically.
- If the API fails, Playwright-based scraping kicks in as fallback.
- Claude tailors resumes by reordering/rewording bullets; it will **never fabricate** experience.
- The `seen_jobs.json` file ensures the same job is never processed twice.
