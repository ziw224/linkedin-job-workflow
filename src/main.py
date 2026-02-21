"""
src/main.py – Daily job-hunt workflow orchestrator.

Parallelization strategy:
  Phase 1 (serial,  ~3 min): Scrape all JDs from LinkedIn
  Phase 2 (parallel, ~8 min): Process jobs with JOB_WORKERS concurrent workers.
      Within each job, resume tailoring and cover-letter generation run in parallel
      (both are independent Claude CLI calls), then PDF is generated from the HTML.

Target: 5 SDE/Fullstack + 5 AI/ML jobs per day → 10 total

Cron (7:30 AM daily — finishes well before 9 AM):
    30 7 * * * /path/to/job-workflow/run.sh
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

import json as _json
from datetime import date as _date
from config.settings import SEEN_JOBS_FILE, TARGET_SDE_JOBS, TARGET_AI_JOBS, JOB_WORKERS, MAX_DAYS_OLD, BASE_RESUME_HTML
from config.user_config import get_user_output_dir, get_user_resume_path, get_resume_pdf_prefix, user_is_ready

from linkedin_scraper import get_new_jobs, _save_seen
from resume_tailor import tailor_resume
from pdf_generator import html_to_pdf
from cover_letter import generate_cover_letter
from notifier import send_discord_report
from progress_notifier import notify_started, notify_scraped, BatchProgressReporter, notify_finished

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

def process_job(job: dict, today_dir: Path, user_ctx: dict) -> dict:
    """
    Full pipeline for one job.

    Args:
        user_ctx: dict with keys base_resume, bio, candidate_name, pdf_prefix
    """
    company_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", job["company"])
    company_dir  = today_dir / company_slug
    company_dir.mkdir(parents=True, exist_ok=True)

    label = f"{job['title']} @ {job['company']}"
    logger.info(f"▶ Starting: {label}")

    html_path = None
    cl_paths  = {"cover_letter": None, "why_company": None}

    with ThreadPoolExecutor(max_workers=2) as inner:
        resume_future = inner.submit(
            tailor_resume, job, company_dir, user_ctx["base_resume"]
        )
        cl_future = inner.submit(
            generate_cover_letter, job, company_dir,
            user_ctx["bio"], user_ctx["candidate_name"]
        )
        html_path = resume_future.result()
        cl_paths  = cl_future.result()

    pdf_path = None
    if html_path:
        pdf_name = f"{user_ctx['pdf_prefix']}-{job['company']}"
        pdf_path = html_to_pdf(html_path, pdf_name=pdf_name)

    success = html_path is not None and pdf_path is not None
    logger.info(f"{'✅' if success else '❌'} Done: {label}")

    return {
        "job":          job,
        "html_path":    html_path,
        "pdf_path":     pdf_path,
        "cover_letter": cl_paths.get("cover_letter"),
        "why_company":  cl_paths.get("why_company"),
        "success":      success,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def run(user_id: str | None = None):
    import time
    t_start = time.time()

    logger.info("=" * 60)
    logger.info(f"Daily Job-Hunt Workflow — starting (user={user_id or 'default'})")
    logger.info(f"Target: {TARGET_SDE_JOBS} SDE + {TARGET_AI_JOBS} AI/ML jobs")
    logger.info(f"Workers: {JOB_WORKERS} | Max age: {MAX_DAYS_OLD}d")
    logger.info("=" * 60)

    # ── Load user-specific config ──────────────────────────────────────────────
    from config.user_config import get_user_profile, get_user_resume_path
    profile = get_user_profile(user_id)
    resume_path = get_user_resume_path(user_id, ai_role=False)

    # Pre-flight: verify resume
    if not resume_path.exists():
        from progress_notifier import _post
        _post(f"⚠️ **Job Hunt aborted** — resume not found for {'<@' + user_id + '>' if user_id else 'default user'}.\nRun `job setup` to register your resume.")
        logger.error(f"Resume not found: {resume_path}")
        return

    resume_content = resume_path.read_text(encoding="utf-8")
    if "yourhandle" in resume_content or "Alex Chen" in resume_content:
        from progress_notifier import _post
        _post("⚠️ **Job Hunt aborted** — resume still has placeholder content.")
        logger.error("Resume contains placeholder content")
        return

    user_ctx = {
        "base_resume":    resume_path,
        "bio":            profile.get("bio", ""),
        "candidate_name": profile.get("name", "Candidate"),
        "pdf_prefix":     profile.get("resume_pdf_prefix", "Resume"),
    }

    notify_started()

    today_dir = get_user_output_dir(user_id) / _date.today().isoformat()
    today_dir.mkdir(parents=True, exist_ok=True)

    # ── Phase 1: Scrape (with automatic fallback) ──────────────────────────────
    logger.info("\n📡 Phase 1: Scraping LinkedIn…")
    selected, seen = get_new_jobs()   # already bucketed + fallback handled

    notify_scraped(len(selected))  # Discord: "📋 Found N jobs..."

    if not selected:
        logger.info("No new jobs found today.")
        send_discord_report([])
        return

    logger.info(f"Proceeding with {len(selected)} jobs")

    # ── Phase 2: Parallel processing ──────────────────────────────────────────
    logger.info(f"\n⚙️  Phase 2: Generating resumes for {len(selected)} jobs (workers={JOB_WORKERS})…")

    results = [None] * len(selected)
    reporter = BatchProgressReporter(total=len(selected))

    with ThreadPoolExecutor(max_workers=JOB_WORKERS) as pool:
        future_to_idx = {
            pool.submit(process_job, job, today_dir, user_ctx): i
            for i, job in enumerate(selected)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                result = future.result()
                results[idx] = result
                label = f"{result['job']['title']} @ {result['job']['company']}"
                reporter.job_done(label, result["success"])
            except Exception as e:
                job = selected[idx]
                logger.error(f"  ❌ Exception processing {job['title']} @ {job['company']}: {e}")
                results[idx] = {
                    "job": job, "html_path": None, "pdf_path": None,
                    "cover_letter": None, "why_company": None, "success": False,
                }
                reporter.job_done(f"{job['title']} @ {job['company']}", False)

    reporter.close()  # flush any remaining progress updates

    # ── Phase 3: Persist + Notify ──────────────────────────────────────────────
    _save_seen(SEEN_JOBS_FILE, seen)
    logger.info(f"Saved {len(seen)} seen job IDs")

    elapsed = int(time.time() - t_start)
    notify_finished(results, elapsed)  # Discord: "✅ Done in Xm Ys"
    send_discord_report(results)        # Discord: full report

    ok = sum(r["success"] for r in results)
    logger.info(f"\n✅ Done in {elapsed//60}m {elapsed%60}s — {ok}/{len(results)} jobs ready")
    logger.info(f"   Output: {today_dir}")


if __name__ == "__main__":
    run()
