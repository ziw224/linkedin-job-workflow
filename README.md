# 🔍 LinkedIn Job-Hunt Workflow

An automated daily pipeline that finds relevant LinkedIn jobs, tailors your resume and cover letter to each posting using Claude AI, generates PDFs, and sends you a Discord summary — all on autopilot.

---

## What it does

```
Every morning (cron)
        │
        ▼
┌───────────────────┐
│  Scrape LinkedIn  │  Search for SDE + AI/ML jobs matching your keywords
│  (Playwright)     │  No login required — uses public job search pages
└────────┬──────────┘
         │  new jobs (deduped)
         ▼
┌───────────────────┐
│  For each job     │  Run in parallel (configurable workers)
│  ┌─────────────┐  │
│  │Tailor Resume│  │  Claude rewrites bullets to match the JD
│  └─────────────┘  │  (surgical edits only — never fabricates experience)
│  ┌─────────────┐  │
│  │Cover Letter │  │  Claude writes a personalized cover letter body
│  └─────────────┘  │
│  ┌─────────────┐  │
│  │ Why Company │  │  Claude writes a 3-5 sentence "Why [company]?" answer
│  └─────────────┘  │
│  ┌─────────────┐  │
│  │  HTML → PDF │  │  Playwright renders the tailored resume to PDF
│  └─────────────┘  │
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  Discord Report   │  Summary with links, status per job
└───────────────────┘
```

**Output per job** (saved to `resume/output/YYYY-MM-DD/{Company}/`):
- `{ID}_{Company}.html` — tailored resume (HTML)
- `{Your Name}-Resume-{Company}.pdf` — print-ready PDF
- `{Your Name}-CoverLetter-{Company}.txt` — cover letter
- `{Your Name}-Why{Company}.txt` — "Why this company?" answer

---

## Requirements

- **Python 3.11+**
- **[Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)** — with an active Claude Max subscription (used for resume tailoring and cover letters; does not consume API credits)
- **Playwright** — for LinkedIn scraping and HTML→PDF rendering
- **Discord webhook** — for daily job report notifications

---

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/job-workflow.git
cd job-workflow
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Playwright browsers

```bash
playwright install chromium
```

### 4. Install Claude Code CLI and log in

Follow the [Claude Code quickstart](https://docs.anthropic.com/en/docs/claude-code). You need a Claude Max subscription.

```bash
# After installing, log in:
claude login
```

Verify it works:
```bash
claude --version
echo "hello" | claude --print "Say hi back"
```

### 5. Set up your Discord webhook

1. Open your Discord server → **Server Settings → Integrations → Webhooks → New Webhook**
2. Pick a channel, copy the webhook URL

### 6. Configure secrets

```bash
cp .env.example .env
```

Edit `.env`:
```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
```

### 7. Fill in your candidate profile

```bash
cp config/candidate_profile.example.json config/candidate_profile.json
```

Edit `config/candidate_profile.json` with **your** info:

```json
{
  "name": "Your Name",
  "email": "you@example.com",
  "portfolio": "yoursite.dev",
  "linkedin": "linkedin.com/in/yourhandle",
  "resume_pdf_prefix": "Your Name-Resume",
  "bio": "Candidate: Your Name\nEducation: ...\n\nWork Experience:\n- ...\n\nKey Projects:\n- ...\n\nTech Stack: ..."
}
```

> **Tip:** The `bio` field is injected verbatim into the cover letter and "Why Company" prompts. Be specific — mention real company names, project names, GPA, publications. The more concrete your bio, the better Claude's output.

### 8. Add your resume

Create `resume/base_resume.html` with your full resume as HTML. This is your **master resume** — Claude edits a copy of it for each job, so keep it up to date.

Optionally, create `resume/base_resume_ai.html` as a separate AI/ML-focused version (if not present, the workflow uses `base_resume.html` for all roles).

> **Resume format tip:** See [Resume Format](#resume-format) below.

### 9. Test run

```bash
python src/main.py
```

Check the output in `resume/output/YYYY-MM-DD/` and your Discord channel.

### 10. Set up daily cron

```bash
crontab -e
```

Add (adjust path as needed):
```
30 7 * * * /path/to/job-workflow/run.sh >> /path/to/job-workflow/logs/cron.log 2>&1
```

This runs at 7:30 AM every day. Adjust the time to your preference.

---

## Configuration

### `config/search_config.json` — Job search behavior

```json
{
  "locations": ["San Francisco, CA", "Remote"],
  "max_days_old": 14,
  "categories": {
    "sde": {
      "keywords": ["Software Engineer", "Full Stack Engineer", ...],
      "experience_levels": [2],
      "target_count": 5
    },
    "ai": {
      "keywords": ["AI Engineer", "ML Engineer", ...],
      "experience_levels": [2, 3],
      "target_count": 5
    }
  }
}
```

| Field | Description |
|---|---|
| `locations` | Locations to search (city or "Remote") |
| `max_days_old` | Skip jobs older than this many days (0 = no limit) |
| `experience_levels` | LinkedIn filter: 1=Intern, 2=Entry, 3=Associate, 4=Mid-Senior |
| `target_count` | How many jobs to process per category per day |
| `job_workers` | Parallel workers for resume generation (2 is safe for Claude Max) |

### `config/candidate_profile.json` — Your personal info

This file is **gitignored** — it stays on your machine only. Fill it in once; the workflow uses it for all cover letters, filenames, and contact info.

### `.env` — Secrets

| Variable | Description |
|---|---|
| `DISCORD_WEBHOOK_URL` | Discord webhook for daily reports |

---

## Project Structure

```
job-workflow/
├── src/
│   ├── main.py               # Orchestrator — phases 1/2/3
│   ├── linkedin_scraper.py   # Playwright-based LinkedIn scraper (no login)
│   ├── resume_tailor.py      # Claude-powered resume tailoring
│   ├── cover_letter.py       # Cover letter + "Why Company" generation
│   ├── pdf_generator.py      # HTML → PDF via Playwright
│   ├── notifier.py           # Discord webhook reporter
│   └── run_one.py            # Quick one-job test runner
├── config/
│   ├── settings.py                       # Reads search_config.json, exposes constants
│   ├── search_config.json                # Job search settings (edit this)
│   ├── candidate_profile.json            # YOUR info (gitignored, create from example)
│   └── candidate_profile.example.json   # Template to copy from
├── resume/
│   ├── base_resume.html      # Your master resume (gitignored)
│   ├── base_resume_ai.html   # AI/ML variant (optional, gitignored)
│   └── output/               # Generated files (gitignored)
│       └── YYYY-MM-DD/
│           └── {Company}/
│               ├── {id}_{Company}.html
│               ├── {Name}-Resume-{Company}.pdf
│               ├── {Name}-CoverLetter-{Company}.txt
│               └── {Name}-Why{Company}.txt
├── data/
│   └── seen_jobs.json        # Dedup tracker (gitignored)
├── logs/
│   └── workflow.log          # Run logs
├── .env                      # Secrets (gitignored)
├── .env.example              # Template
├── requirements.txt
└── run.sh                    # Cron entry point
```

---

## How It Works

### Phase 1 — LinkedIn Scraping (`linkedin_scraper.py`)

Uses Playwright (headless Chromium) to scrape LinkedIn's **public job search pages** — no login required. Two passes per search:

1. **Card pass** — collect job metadata (title, company, location, URL, posted date) from search result cards
2. **Detail pass** — visit each job URL to fetch the full job description text

Jobs are filtered by recency (`max_days_old`) and deduplicated against `data/seen_jobs.json`.

If the primary scrape yields fewer jobs than `target_count`, **fallback stages** automatically retry with relaxed filters (wider time window, more experience levels). See `search_config.json → fallback.stages`.

### Phase 2 — Parallel Processing (`main.py`)

Each job is processed by a worker thread:
- **Resume tailoring** and **cover letter generation** run **in parallel** (both are independent Claude calls)
- **PDF generation** waits for the tailored HTML, then renders it to PDF

### Resume Tailoring (`resume_tailor.py`)

Claude receives:
- The full job description
- Your HTML resume body
- A strict prompt that enforces **surgical edits only**: reorder bullets, weave in keywords — never fabricate experience, never rewrite from scratch

The first bullet of each `<ul>` is automatically "locked" (`data-lock="1"`) to prevent Claude from moving your headline achievements.

Role detection picks between your SWE resume and AI/ML resume based on job title and JD keywords.

### Cover Letters & Why Company (`cover_letter.py`)

Two separate Claude calls per job:
1. **Cover letter** — 3-4 paragraph body (320 words max), warm and specific to the company
2. **Why company** — 3-5 sentence answer grounded in the actual role responsibilities (not generic company praise)

Both use your `candidate_profile.json` bio as context.

---

## Resume Format

Your `base_resume.html` should be a single-file HTML resume with inline CSS. The workflow:
- Extracts the `<body>` content and sends it to Claude
- Re-wraps Claude's output in your original HTML shell (preserving CSS)
- Renders to PDF with Playwright

**Data-lock attribute:** The first `<li>` in each `<ul>` is automatically marked `data-lock="1"` before sending to Claude. This tells Claude it cannot move that bullet from position 1. You don't need to add this manually.

**One page:** The PDF generator automatically scales the content to fit exactly one page. Content taller than Letter size is scaled down proportionally.

---

## Customization

**Change target roles:** Edit `config/search_config.json` → `categories`

**Change locations:** Edit `config/search_config.json` → `locations`

**Adjust daily targets:** Edit `target_count` per category

**Modify resume tailoring rules:** Edit `PROMPT_TEMPLATE` in `src/resume_tailor.py`

**Modify cover letter style:** Edit `COVER_LETTER_PROMPT` / `WHY_COMPANY_PROMPT` in `src/cover_letter.py`

---

## Troubleshooting

**`FileNotFoundError: Claude CLI not found`**
→ Install Claude Code from https://docs.anthropic.com/en/docs/claude-code and ensure it's on your PATH. Run `which claude` to verify.

**`No jobs found today`**
→ LinkedIn's public pages change their HTML structure occasionally. Check `logs/workflow.log` for scraper errors. You may need to update the CSS selectors in `linkedin_scraper.py` (look for `.job-search-card`, `.base-search-card__title`, etc.).

**`Claude returned empty output` / resume tailoring fails**
→ Run `echo "test" | claude --print "Say hello"` to verify Claude CLI is working. Check that you're logged in with `claude auth status`.

**PDF is two pages**
→ The PDF generator applies CSS scaling automatically. If it's still two pages, your resume HTML may have hardcoded heights or overflow issues. Simplify the CSS.

**Discord webhook not sending**
→ Verify `DISCORD_WEBHOOK_URL` is set in `.env` and the webhook URL is valid. Test with:
```bash
curl -X POST "$DISCORD_WEBHOOK_URL" -H 'Content-Type: application/json' -d '{"content": "test"}'
```

**Rate limiting from LinkedIn**
→ The scraper adds random delays between requests. If you're hitting limits, increase `base` and `jitter` in `_safe_sleep()` in `linkedin_scraper.py`, or reduce `max_candidates`.

---

## License

MIT — do whatever you want, just don't spam LinkedIn aggressively. Be polite with request rates.
