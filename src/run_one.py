#!/usr/bin/env python3
"""One-shot: scrape 1 LinkedIn job, tailor, PDF, notify."""
import logging
import re
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "run_one.log"),
    ],
)
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import json as _json
from config.settings import OUTPUT_DIR

_profile_path = PROJECT_ROOT / "config" / "candidate_profile.json"
_RESUME_PDF_PREFIX = "Resume"
if _profile_path.exists():
    with open(_profile_path) as _pf:
        _RESUME_PDF_PREFIX = _json.load(_pf).get("resume_pdf_prefix", "Resume")
from linkedin_scraper import scrape_with_playwright
from resume_tailor import tailor_resume
from pdf_generator import html_to_pdf
from notifier import send_discord_report

def main():
    today_dir = OUTPUT_DIR / date.today().isoformat()
    today_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Scraping LinkedIn (1 job)...")
    jobs = scrape_with_playwright(set())

    if not jobs:
        logger.error("No jobs found. Check LinkedIn selectors.")
        return

    job = jobs[0]
    logger.info(f"Found: {job['title']} @ {job['company']} | {job['location']}")
    logger.info(f"URL: {job['url']}")

    company_dir = today_dir / re.sub(r"[^a-zA-Z0-9_-]", "_", job["company"])
    company_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Tailoring resume via Claude...")
    html = tailor_resume(job, output_dir=company_dir)
    if not html:
        logger.error("Tailoring failed.")
        return

    pdf = html_to_pdf(html, f"{_RESUME_PDF_PREFIX}-{job['company']}")
    ok  = pdf is not None

    send_discord_report([{"job": job, "html_path": html, "pdf_path": pdf, "success": ok}])
    logger.info(f"Done! Files in: {company_dir}")
    logger.info(f"  HTML: {html.name}")
    if pdf:
        logger.info(f"  PDF:  {pdf.name}")

if __name__ == "__main__":
    main()
