"""
src/main.py – Daily job-hunt workflow orchestrator.

Parallelization strategy:
  Phase 1 (serial,  ~3 min): Scrape all JDs from LinkedIn
  Phase 2 (parallel, ~8 min): Process jobs with JOB_WORKERS concurrent workers.
      Within each job, resume tailoring and cover-letter generation run in parallel
      (both are independent Claude CLI calls), then PDF is generated from the HTML.

Target: 5 SDE/Fullstack + 5 AI/ML jobs per day → 10 total

Cron (7:30 AM daily — finishes well before 9 AM):
    0 9 * * * cd $HOME/Projects/linkedin-job-workflow && bash run.sh >> logs/cron.log 2>&1
"""
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Ensure project root and src are on sys.path regardless of where we're called from
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
SRC_DIR      = PROJECT_ROOT / "src"
for p in (str(PROJECT_ROOT), str(SRC_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv  # type: ignore
load_dotenv(PROJECT_ROOT / ".env")

from datetime import date as _date
import os
from config.settings import OUTPUT_DIR, SEEN_JOBS_FILE, TARGET_SDE_JOBS, TARGET_AI_JOBS, JOB_WORKERS, MAX_DAYS_OLD
from linkedin_scraper import get_new_jobs, _save_seen
from resume_tailor import tailor_resume
from pdf_generator import html_to_pdf
from cover_letter import generate_cover_letter
from notifier import send_discord_report
from notion_tracker import add_jobs_to_notion

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "workflow.log"),
    ],
)
logger = logging.getLogger(__name__)


# ── Per-job worker ─────────────────────────────────────────────────────────────

def process_job(job: dict, today_dir: Path) -> dict:
    """
    Full pipeline for one job:
      1. tailor_resume + generate_cover_letter in parallel (both need only job dict)
      2. html_to_pdf after resume is ready

    Returns result dict with html_path, pdf_path, cover_letter, why_company, success.
    """
    company_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", job["company"])
    company_dir  = today_dir / company_slug
    company_dir.mkdir(parents=True, exist_ok=True)

    label = f"{job['title']} @ {job['company']}"
    logger.info(f"▶ Starting: {label}")

    html_path = None
    cl_paths  = {"cover_letter": None, "why_company": None}

    # Run resume tailoring and cover letter generation in parallel
    with ThreadPoolExecutor(max_workers=2) as inner:
        resume_future = inner.submit(tailor_resume, job, company_dir)
        cl_future     = inner.submit(generate_cover_letter, job, company_dir)

        html_path = resume_future.result()
        cl_paths  = cl_future.result()

    # PDF must wait for html_path
    pdf_path = None
    if html_path:
        candidate_name = os.getenv("CANDIDATE_NAME", "Resume")
        pdf_name = f"{candidate_name}-Resume-{job['company']}"
        pdf_path = html_to_pdf(html_path, pdf_name=pdf_name)

    success = html_path is not None and pdf_path is not None
    status  = "✅" if success else "❌"
    logger.info(f"{status} Done: {label}")

    return {
        "job":          job,
        "html_path":    html_path,
        "pdf_path":     pdf_path,
        "cover_letter": cl_paths.get("cover_letter"),
        "why_company":  cl_paths.get("why_company"),
        "success":      success,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def run():
    import time
    t_start = time.time()

    llm_mode = os.getenv("LLM_MODE", "claude").strip().lower()
    workers = JOB_WORKERS
    if llm_mode == "openclaw" and workers > 1:
        workers = 1  # avoid openclaw session lock contention in parallel workers

    logger.info("=" * 60)
    logger.info("Daily Job-Hunt Workflow — starting")
    logger.info(f"Target: {TARGET_SDE_JOBS} SDE + {TARGET_AI_JOBS} AI/ML jobs")
    logger.info(f"Workers: {workers} | Max age: {MAX_DAYS_OLD}d | LLM_MODE: {llm_mode}")
    logger.info("=" * 60)

    today_dir = OUTPUT_DIR / _date.today().isoformat()
    today_dir.mkdir(parents=True, exist_ok=True)

    # ── Phase 1: Scrape (with automatic fallback) ──────────────────────────────
    logger.info("\n📡 Phase 1: Scraping LinkedIn…")
    selected, seen = get_new_jobs(on_progress=lambda msg: print(msg, flush=True))

    if not selected:
        logger.info("No new jobs found today.")
        send_discord_report([])
        return

    logger.info(f"Proceeding with {len(selected)} jobs")

    # ── Save job manifest (for retry-day) ──────────────────────────────────────
    import json as _json
    jobs_log_path = PROJECT_ROOT / "data" / f"jobs_{_date.today().isoformat()}.json"
    jobs_log_path.parent.mkdir(exist_ok=True)
    # Merge with any existing manifest (in case of multiple runs same day)
    existing = {}
    if jobs_log_path.exists():
        try:
            for j in _json.loads(jobs_log_path.read_text()):
                existing[j["url"]] = j
        except Exception:
            pass
    for j in selected:
        existing[j["url"]] = {k: j[k] for k in ("title","company","location","url","category") if k in j}
    jobs_log_path.write_text(_json.dumps(list(existing.values()), ensure_ascii=False, indent=2))
    logger.info(f"Job manifest saved → {jobs_log_path.name}")

    # ── Phase 2: Parallel processing ──────────────────────────────────────────
    logger.info(f"\n⚙️  Phase 2: Generating resumes for {len(selected)} jobs (workers={workers})…")

    results = [None] * len(selected)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_idx = {
            pool.submit(process_job, job, today_dir): i
            for i, job in enumerate(selected)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                job = selected[idx]
                logger.error(f"  ❌ Exception processing {job['title']} @ {job['company']}: {e}")
                results[idx] = {
                    "job": job, "html_path": None, "pdf_path": None,
                    "cover_letter": None, "why_company": None, "success": False,
                }

    # ── Phase 3: Persist + Notify ──────────────────────────────────────────────
    _save_seen(SEEN_JOBS_FILE, seen)
    logger.info(f"Saved {len(seen)} seen job IDs")

    send_discord_report(results)
    add_jobs_to_notion(results, only_success=False)  # add all scraped jobs; dedup prevents duplicates on retry

    elapsed = int(time.time() - t_start)
    ok = sum(r["success"] for r in results)
    logger.info(f"\n✅ Done in {elapsed//60}m {elapsed%60}s — {ok}/{len(results)} jobs ready")
    logger.info(f"   Output: {today_dir}")


if __name__ == "__main__":
    run()
