#!/usr/bin/env python3
"""
src/cli.py – Quick CLI wrapper for the job-hunt workflow.

Commands:
  scrape             Scrape LinkedIn jobs (no tailoring) — prints JSON
  run                Run full pipeline (scrape + tailor + PDF + Discord)
  retry <url>        Re-run pipeline for a single LinkedIn job URL
  status             Print today's output summary
  model <target>     Switch generation model backend in .env
                     targets: claude | openclaw | codex

Usage:
  python src/cli.py scrape
  python src/cli.py run
  python src/cli.py retry "https://www.linkedin.com/jobs/view/1234567890/"
  python src/cli.py retry "https://..." --title "AI Engineer" --company "Acme" --category ai
  python src/cli.py status
  python src/cli.py model codex
"""

import json
import logging
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
for p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

(PROJECT_ROOT / "logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(PROJECT_ROOT / "logs" / "workflow.log"),
    ],
)


def cmd_scrape():
    """Scrape LinkedIn for new jobs and print a JSON list to stdout.
    Uses max_candidates_preview (smaller limit) for speed."""
    from linkedin_scraper import scrape_with_playwright
    from config.settings import SEEN_JOBS_FILE
    import config.settings as _settings

    cfg_path = PROJECT_ROOT / "config" / "search_config.json"
    cfg = json.load(open(cfg_path))
    preview_limit = cfg.get("max_candidates_preview", 20)

    # Patch both settings module and the already-imported scraper module
    import linkedin_scraper as _scraper
    original_limit = _settings.MAX_JOBS_PER_RUN
    _settings.MAX_JOBS_PER_RUN = preview_limit
    _scraper.MAX_JOBS_PER_RUN  = preview_limit

    seen: set[str] = set()
    if SEEN_JOBS_FILE.exists():
        seen = set(json.load(open(SEEN_JOBS_FILE)).get("seen_ids", []))

    try:
        jobs = scrape_with_playwright(seen)
    finally:
        _settings.MAX_JOBS_PER_RUN = original_limit
        _scraper.MAX_JOBS_PER_RUN  = original_limit

    output = []
    for j in jobs:
        age = f"{j['days_old']}d ago" if j.get("days_old", -1) >= 0 else "unknown age"
        output.append({
            "title":    j["title"],
            "company":  j["company"],
            "location": j["location"],
            "url":      j["url"],
            "age":      age,
            "snippet":  j.get("description", "")[:200].replace("\n", " ").strip(),
        })

    print(json.dumps(output, ensure_ascii=False))


def cmd_run():
    """Run the full daily job-hunt pipeline."""
    import main
    main.run()


def _upsert_env_vars(path: Path, updates: dict[str, str]) -> None:
    """Update/create key=value pairs in .env while preserving other lines."""
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    seen = set()
    out: list[str] = []
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in updates:
                out.append(f"{k}={updates[k]}")
                seen.add(k)
                continue
        out.append(line)

    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")

    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def cmd_model(target: str | None = None, agent: str | None = None):
    """Switch LLM backend via .env.

    target:
      - claude
      - openclaw [agent]
      - codex (shortcut for openclaw + coding)
    """
    env_path = PROJECT_ROOT / ".env"

    if not target:
        print("Usage: python src/cli.py model <claude|openclaw|codex> [agent]")
        return

    t = target.strip().lower()
    if t == "claude":
        _upsert_env_vars(env_path, {"LLM_MODE": "claude"})
        print("✅ Model set: claude")
        return

    if t == "codex":
        _upsert_env_vars(env_path, {"LLM_MODE": "codex"})
        print("✅ Model set: codex (direct codex CLI)")
        return
    
    print(f"❌ Unknown model target: {target}")
    print("Usage: python src/cli.py model <claude|openclaw|codex> [agent]")


def cmd_status():
    """Print today's output summary as JSON."""
    from config.settings import OUTPUT_DIR

    today = date.today().isoformat()
    today_dir = OUTPUT_DIR / today

    result = {"date": today, "companies": [], "total": 0, "ok": 0}

    if today_dir.exists():
        for comp_dir in sorted(today_dir.iterdir()):
            if not comp_dir.is_dir():
                continue
            files = list(comp_dir.iterdir())
            has_pdf = any(f.suffix == ".pdf" for f in files)
            result["companies"].append({
                "name":    comp_dir.name,
                "success": has_pdf,
                "files":   [f.name for f in sorted(files)],
            })
        result["total"] = len(result["companies"])
        result["ok"]    = sum(1 for c in result["companies"] if c["success"])

    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_retry(url: str, title: str = "", company: str = "", location: str = "San Francisco", category: str = "sde"):
    """Re-run full pipeline (tailor + cover letter + PDF + Notion) for a single LinkedIn job URL.

    Usage:
      python src/cli.py retry <url>
      python src/cli.py retry <url> --title "AI Engineer" --company "Acme" --location "Remote" --category ai
    """
    import re as _re
    from playwright.sync_api import sync_playwright

    logging.info(f"Fetching JD from: {url}")

    job: dict = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, timeout=30_000)
            page.wait_for_timeout(2000)

            # Extract JD text
            description = ""
            for sel in [".show-more-less-html__markup", "#job-details", ".description__text"]:
                el = page.query_selector(sel)
                if el:
                    description = el.inner_text().strip()
                    break

            # Extract title / company / location if not provided
            if not title:
                el = page.query_selector("h1")
                title = el.inner_text().strip() if el else "Software Engineer"
            if not company:
                el = page.query_selector(".topcard__org-name-link, .job-details-jobs-unified-top-card__company-name a")
                company = el.inner_text().strip() if el else "Unknown Company"
            if not location or location == "San Francisco":
                el = page.query_selector(".topcard__flavor--bullet, .job-details-jobs-unified-top-card__bullet")
                if el:
                    location = el.inner_text().strip()

            job = {
                "title":       title,
                "company":     company,
                "location":    location,
                "url":         url.split("?")[0],
                "description": description,
                "category":    category,
            }
        finally:
            browser.close()

    if not job:
        logging.error("Failed to fetch job data.")
        return

    logging.info(f"Job: {job['title']} @ {job['company']} | {job['location']}")
    if not job["description"]:
        logging.warning("JD text empty — cover letter may be generic")

    # Run pipeline
    import shutil as _shutil
    from config.settings import OUTPUT_DIR
    from main import process_job
    from notion_tracker import add_jobs_to_notion

    today_dir = OUTPUT_DIR / date.today().isoformat()
    today_dir.mkdir(parents=True, exist_ok=True)

    result = process_job(job, today_dir)
    logging.info(f"{'✅' if result['success'] else '❌'} Done: {job['title']} @ {job['company']}")

    # Sync to Notion + Drive, then clean up local files
    drive_url_map = add_jobs_to_notion([result])

    # Update today's manifest with Drive URL
    manifest_path = PROJECT_ROOT / "data" / f"jobs_{date.today().isoformat()}.json"
    if drive_url_map and manifest_path.exists():
        try:
            import json as _json
            entries = _json.loads(manifest_path.read_text())
            for entry in entries:
                if entry.get("url") in drive_url_map:
                    entry["drive_url"] = drive_url_map[entry["url"]]
            manifest_path.write_text(_json.dumps(entries, ensure_ascii=False, indent=2))
        except Exception:
            pass

    # Delete local company folder — files are on Drive
    company_slug = _re.sub(r"[^a-zA-Z0-9_-]", "_", job["company"])
    company_dir = today_dir / company_slug
    if company_dir.exists():
        _shutil.rmtree(company_dir, ignore_errors=True)
        logging.info(f"Local files cleaned up: {company_dir.name}")


def cmd_retry_day(day: str | None = None):
    """Re-run pipeline for all failed jobs on a given day.

    Reads data/jobs_YYYY-MM-DD.json (saved automatically each run),
    checks which companies have no PDF in resume/output/YYYY-MM-DD/,
    and re-processes those jobs.

    Usage:
      python src/cli.py retry-day             # today
      python src/cli.py retry-day 2026-02-23  # specific date
    """
    import json as _json
    import re as _re
    from config.settings import OUTPUT_DIR
    from main import process_job
    from notion_tracker import add_jobs_to_notion

    target_date = day or date.today().isoformat()
    manifest_path = PROJECT_ROOT / "data" / f"jobs_{target_date}.json"

    if not manifest_path.exists():
        logging.error(f"No job manifest found for {target_date}: {manifest_path}")
        logging.info("Hint: manifests are saved automatically starting from the next run.")
        return

    jobs = _json.loads(manifest_path.read_text())
    today_dir = OUTPUT_DIR / target_date
    today_dir.mkdir(parents=True, exist_ok=True)

    # A job is "done" if it has a drive_url in the manifest (files live on Drive, not local disk)
    failed = [j for j in jobs if not j.get("drive_url")]

    if not failed:
        logging.info(f"✅ All jobs for {target_date} already on Drive — nothing to retry.")
        return

    logging.info(f"Found {len(failed)} failed jobs for {target_date}, re-running…")
    for j in failed:
        logging.info(f"  → {j['title']} @ {j['company']}")

    results = []
    for job in failed:
        # If no description cached, fetch from LinkedIn
        if not job.get("description"):
            logging.info(f"Fetching JD for {job['title']} @ {job['company']}…")
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.goto(job["url"], timeout=30_000)
                    page.wait_for_timeout(2000)
                    description = ""
                    for sel in [".show-more-less-html__markup", "#job-details", ".description__text"]:
                        el = page.query_selector(sel)
                        if el:
                            description = el.inner_text().strip()
                            break
                    browser.close()
                job["description"] = description
            except Exception as e:
                logging.warning(f"  JD fetch failed: {e} — continuing without JD")
                job["description"] = ""

        result = process_job(job, today_dir)
        results.append(result)
        status = "✅" if result["success"] else "❌"
        logging.info(f"  {status} {job['title']} @ {job['company']}")

    import shutil as _shutil
    ok = sum(r["success"] for r in results)
    logging.info(f"\nDone — {ok}/{len(results)} jobs succeeded")

    if results:
        drive_url_map = add_jobs_to_notion([r for r in results if r["success"]])

        # Update manifest with Drive URLs
        if drive_url_map:
            try:
                all_entries = _json.loads(manifest_path.read_text())
                for entry in all_entries:
                    if entry.get("url") in drive_url_map:
                        entry["drive_url"] = drive_url_map[entry["url"]]
                manifest_path.write_text(_json.dumps(all_entries, ensure_ascii=False, indent=2))
            except Exception:
                pass

        # Clean up local company dirs — files are on Drive
        for r in results:
            if r.get("success"):
                company_slug = _re.sub(r"[^a-zA-Z0-9_-]", "_", r["job"]["company"])
                comp_dir = today_dir / company_slug
                if comp_dir.exists():
                    _shutil.rmtree(comp_dir, ignore_errors=True)


COMMANDS = {"scrape": cmd_scrape, "run": cmd_run, "retry": cmd_retry, "retry-day": cmd_retry_day, "status": cmd_status, "model": cmd_model}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python src/cli.py [{' | '.join(COMMANDS)}]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"Usage: python src/cli.py [{' | '.join(COMMANDS)}]", file=sys.stderr)
        sys.exit(1)

    if cmd == "model":
        target = sys.argv[2] if len(sys.argv) > 2 else None
        agent = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_model(target, agent)
    elif cmd == "retry":
        if len(sys.argv) < 3:
            print("Usage: python src/cli.py retry <linkedin_url> [--title ...] [--company ...] [--location ...] [--category sde|ai]")
            sys.exit(1)
        url = sys.argv[2]
        kwargs: dict = {}
        args = sys.argv[3:]
        i = 0
        while i < len(args):
            if args[i] in ("--title", "--company", "--location", "--category") and i + 1 < len(args):
                kwargs[args[i].lstrip("-")] = args[i + 1]
                i += 2
            else:
                i += 1
        cmd_retry(url, **kwargs)
    elif cmd == "retry-day":
        day = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_retry_day(day)
    else:
        COMMANDS[cmd]()
