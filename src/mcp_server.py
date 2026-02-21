"""
src/mcp_server.py – MCP server for the LinkedIn Job-Hunt Workflow.

Exposes the workflow as tools for Claude Desktop, Cursor, or any
MCP-compatible client. Users can invoke the full pipeline or individual
steps via natural language — no terminal required.

Setup (Claude Desktop):
  Add to ~/Library/Application Support/Claude/claude_desktop_config.json:
  {
    "mcpServers": {
      "job-hunt": {
        "command": "/opt/homebrew/Caskroom/miniconda/base/bin/python3",
        "args": ["/ABSOLUTE/PATH/TO/job-workflow/src/mcp_server.py"]
      }
    }
  }

Run standalone (test):
  python src/mcp_server.py
"""

import io
import json
import logging
import re
import sys
from datetime import date, datetime
from pathlib import Path

# ── Project root on sys.path ───────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
for p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from mcp.server.fastmcp import FastMCP

# ── MCP server instance ────────────────────────────────────────────────────────
mcp = FastMCP(
    name="job-hunt",
    instructions=(
        "This server automates LinkedIn job hunting. "
        "Use run_workflow to run the full daily pipeline. "
        "Use scrape_jobs to preview today's openings. "
        "Use tailor_job to tailor a resume for a specific job URL or description. "
        "Use get_status to check today's output. "
        "Use get_config to see current search settings."
    ),
)


# ── Helper: capture logs ───────────────────────────────────────────────────────
def _capture_logs(func, *args, **kwargs):
    """Run func(*args, **kwargs), capture all log output, return (result, log_str)."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        result = func(*args, **kwargs)
    finally:
        root.removeHandler(handler)
    return result, buf.getvalue()


# ── Tool 1: run_workflow ───────────────────────────────────────────────────────
@mcp.tool()
def run_workflow(dry_run: bool = False) -> str:
    """
    Run the full daily job-hunt pipeline: scrape LinkedIn, tailor resumes
    with Claude AI, generate PDFs, and send a Discord report.

    Set dry_run=True to only scrape jobs and preview them without
    generating resumes, cover letters, or sending notifications.

    Returns a summary of what was processed.
    """
    try:
        if dry_run:
            from linkedin_scraper import get_new_jobs
            jobs, _ = get_new_jobs()
            if not jobs:
                return "No new jobs found today."
            lines = [f"🔍 Dry run — found {len(jobs)} new job(s):\n"]
            for i, j in enumerate(jobs, 1):
                lines.append(f"{i}. {j['title']} @ {j['company']} | {j['location']}")
                lines.append(f"   {j['url']}\n")
            return "\n".join(lines)

        import time
        from config.settings import OUTPUT_DIR, SEEN_JOBS_FILE, TARGET_SDE_JOBS, TARGET_AI_JOBS, JOB_WORKERS
        from linkedin_scraper import get_new_jobs, _save_seen
        from resume_tailor import tailor_resume
        from pdf_generator import html_to_pdf
        from cover_letter import generate_cover_letter
        from notifier import send_discord_report
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import json as _json

        # Load PDF prefix from candidate profile
        profile_path = PROJECT_ROOT / "config" / "candidate_profile.json"
        pdf_prefix = "Resume"
        if profile_path.exists():
            with open(profile_path) as f:
                pdf_prefix = _json.load(f).get("resume_pdf_prefix", "Resume")

        today_dir = OUTPUT_DIR / date.today().isoformat()
        today_dir.mkdir(parents=True, exist_ok=True)

        t_start = time.time()
        status_lines = ["🚀 Job-hunt workflow started...\n"]

        # Phase 1: Scrape
        status_lines.append("📡 Phase 1: Scraping LinkedIn...")
        jobs, seen = get_new_jobs()

        if not jobs:
            return "No new jobs found today. Try again tomorrow or adjust search_config.json."

        status_lines.append(f"Found {len(jobs)} new job(s) to process.\n")
        status_lines.append("⚙️  Phase 2: Tailoring resumes in parallel...")

        # Phase 2: Parallel processing
        def _process(job):
            company_dir = today_dir / re.sub(r"[^a-zA-Z0-9_-]", "_", job["company"])
            company_dir.mkdir(parents=True, exist_ok=True)
            html = tailor_resume(job, company_dir)
            cl   = generate_cover_letter(job, company_dir)
            pdf  = html_to_pdf(html, f"{pdf_prefix}-{job['company']}") if html else None
            return {
                "job": job, "html_path": html, "pdf_path": pdf,
                "cover_letter": cl.get("cover_letter"),
                "why_company":  cl.get("why_company"),
                "success": html is not None and pdf is not None,
            }

        results = []
        with ThreadPoolExecutor(max_workers=JOB_WORKERS) as pool:
            futures = {pool.submit(_process, j): j for j in jobs}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    job = futures[future]
                    results.append({"job": job, "success": False,
                                    "html_path": None, "pdf_path": None,
                                    "cover_letter": None, "why_company": None})

        # Phase 3: Save + notify
        _save_seen(SEEN_JOBS_FILE, seen)
        send_discord_report(results)

        elapsed = int(time.time() - t_start)
        ok = sum(r["success"] for r in results)

        status_lines.append(f"\n✅ Done in {elapsed//60}m {elapsed%60}s\n")
        status_lines.append(f"Processed {len(results)} job(s) — {ok} succeeded, {len(results)-ok} failed\n")
        status_lines.append(f"📁 Output: {today_dir}\n\nJobs processed:")
        for r in results:
            j = r["job"]
            icon = "✅" if r["success"] else "❌"
            status_lines.append(f"  {icon} {j['title']} @ {j['company']}")

        return "\n".join(status_lines)

    except Exception as e:
        return f"❌ Workflow error: {e}"


# ── Tool 2: scrape_jobs ────────────────────────────────────────────────────────
@mcp.tool()
def scrape_jobs() -> str:
    """
    Scrape LinkedIn for new jobs matching your configured keywords and locations.
    Returns a list of found jobs without processing them (no resume tailoring,
    no Claude calls, no changes to seen_jobs.json).

    Useful for previewing what's available before committing to a full run.
    """
    try:
        from linkedin_scraper import scrape_with_playwright
        from config.settings import SEEN_JOBS_FILE
        import json as _json

        # Load seen IDs for dedup preview, but don't save
        seen: set[str] = set()
        if SEEN_JOBS_FILE.exists():
            with open(SEEN_JOBS_FILE) as f:
                seen = set(_json.load(f).get("seen_ids", []))

        jobs = scrape_with_playwright(seen)

        if not jobs:
            return "No new jobs found. LinkedIn may be rate-limiting or selectors need updating."

        lines = [f"🔍 Found {len(jobs)} new job(s):\n"]
        for i, j in enumerate(jobs, 1):
            age = f"{j['days_old']}d ago" if j.get("days_old", -1) >= 0 else "unknown age"
            lines.append(f"{i}. **{j['title']}** @ {j['company']}")
            lines.append(f"   📍 {j['location']}  •  🕐 {age}")
            lines.append(f"   🔗 {j['url']}")
            if j.get("description"):
                snippet = j["description"][:200].replace("\n", " ").strip()
                lines.append(f"   📄 {snippet}...")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Scrape error: {e}"


# ── Tool 3: tailor_job ─────────────────────────────────────────────────────────
@mcp.tool()
def tailor_job(
    url: str = "",
    title: str = "",
    company: str = "",
    description: str = "",
) -> str:
    """
    Tailor your resume and generate a cover letter + 'Why this company?' answer
    for a single job. Provide either:
      - url: a LinkedIn job URL (the tool fetches the full JD), or
      - description: the job description text directly

    title and company are optional but improve output quality.
    Returns paths to all generated files.
    """
    try:
        from resume_tailor import tailor_resume
        from cover_letter import generate_cover_letter
        from pdf_generator import html_to_pdf
        import json as _json

        # Load PDF prefix
        profile_path = PROJECT_ROOT / "config" / "candidate_profile.json"
        pdf_prefix = "Resume"
        if profile_path.exists():
            with open(profile_path) as f:
                pdf_prefix = _json.load(f).get("resume_pdf_prefix", "Resume")

        jd = description.strip()

        # If URL provided and no description, scrape the JD
        if url and not jd:
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.goto(url, timeout=25_000)
                    page.wait_for_timeout(3000)
                    for sel in [".show-more-less-html__markup", "#job-details", ".description__text"]:
                        el = page.query_selector(sel)
                        if el:
                            jd = el.inner_text().strip()
                            break
                    # Try to extract title/company from page if not provided
                    if not title:
                        el = page.query_selector("h1")
                        if el:
                            title = el.inner_text().strip()
                    if not company:
                        el = page.query_selector(".topcard__org-name-link, .sub-nav-cta__optional-url")
                        if el:
                            company = el.inner_text().strip()
                    browser.close()
            except Exception as e:
                return f"❌ Could not fetch JD from URL: {e}"

        if not jd and not url:
            return "❌ Please provide either a LinkedIn job URL or a job description."

        company = company or "Company"
        title   = title   or "Software Engineer"

        job = {
            "job_id":      "manual",
            "title":       title,
            "company":     company,
            "location":    "",
            "url":         url,
            "description": jd,
        }

        out_dir = PROJECT_ROOT / "resume" / "output" / date.today().isoformat() / re.sub(r"[^a-zA-Z0-9_-]", "_", company)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Tailor resume + cover letter in parallel
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            resume_f = pool.submit(tailor_resume, job, out_dir)
            cover_f  = pool.submit(generate_cover_letter, job, out_dir)
            html_path = resume_f.result()
            cl_paths  = cover_f.result()

        pdf_path = html_to_pdf(html_path, f"{pdf_prefix}-{company}") if html_path else None

        lines = [f"✅ Tailored for: **{title}** @ **{company}**\n", "📁 Generated files:"]
        def _rel(p):
            return str(p.relative_to(PROJECT_ROOT)) if p else "—"
        lines.append(f"  • Resume HTML:    {_rel(html_path)}")
        lines.append(f"  • Resume PDF:     {_rel(pdf_path)}")
        lines.append(f"  • Cover Letter:   {_rel(cl_paths.get('cover_letter'))}")
        lines.append(f"  • Why {company}: {_rel(cl_paths.get('why_company'))}")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ tailor_job error: {e}"


# ── Tool 4: get_status ─────────────────────────────────────────────────────────
@mcp.tool()
def get_status() -> str:
    """
    Get the status of today's job-hunt run: which companies were processed,
    how many files were generated, and the last log entries.
    """
    try:
        from config.settings import OUTPUT_DIR

        today = date.today().isoformat()
        today_dir = OUTPUT_DIR / today

        lines = [f"📊 Job-Hunt Status — {today}\n"]

        if not today_dir.exists():
            lines.append("No output found for today. Run `run_workflow` to start.")
        else:
            companies = [d for d in today_dir.iterdir() if d.is_dir()]
            lines.append(f"Companies processed: {len(companies)}")
            lines.append("")
            for comp_dir in sorted(companies):
                files = list(comp_dir.iterdir())
                pdfs  = [f for f in files if f.suffix == ".pdf"]
                htmls = [f for f in files if f.suffix == ".html"]
                txts  = [f for f in files if f.suffix == ".txt"]
                status = "✅" if pdfs else "⚠️"
                lines.append(f"  {status} {comp_dir.name}")
                lines.append(f"     HTML: {len(htmls)}  PDF: {len(pdfs)}  TXT: {len(txts)}")

        # Last log lines
        log_file = PROJECT_ROOT / "logs" / "workflow.log"
        if log_file.exists():
            log_lines = log_file.read_text().splitlines()
            recent = log_lines[-15:] if len(log_lines) > 15 else log_lines
            lines.append("\n📋 Recent logs:")
            lines.extend(f"  {l}" for l in recent)

        return "\n".join(lines)

    except Exception as e:
        return f"❌ get_status error: {e}"


# ── Tool 5: get_config ─────────────────────────────────────────────────────────
@mcp.tool()
def get_config() -> str:
    """
    Show the current job search configuration: keywords, locations,
    experience levels, target counts, and fallback stages.
    """
    try:
        cfg_path = PROJECT_ROOT / "config" / "search_config.json"
        with open(cfg_path) as f:
            cfg = json.load(f)

        # Remove comment keys for cleaner output
        def strip_comments(obj):
            if isinstance(obj, dict):
                return {k: strip_comments(v) for k, v in obj.items() if not k.startswith("_")}
            if isinstance(obj, list):
                return [strip_comments(i) for i in obj]
            return obj

        clean = strip_comments(cfg)
        return f"⚙️  Current search configuration:\n\n{json.dumps(clean, indent=2)}"

    except Exception as e:
        return f"❌ get_config error: {e}"


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run()
