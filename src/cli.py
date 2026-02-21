#!/usr/bin/env python3
"""
src/cli.py – Quick CLI wrapper for the job-hunt skill.

Commands:
  scrape   Scrape LinkedIn jobs (no tailoring) — prints JSON to stdout
  run      Run the full daily pipeline (scrape + tailor + PDF + Discord)
  status   Print today's output summary

Usage (called by OpenClaw job-hunt skill):
  python src/cli.py scrape
  python src/cli.py run
  python src/cli.py status
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(PROJECT_ROOT / "logs" / "workflow.log")],
)


def cmd_scrape():
    """Scrape LinkedIn for new jobs and print a JSON list to stdout."""
    from linkedin_scraper import scrape_with_playwright
    from config.settings import SEEN_JOBS_FILE

    seen: set[str] = set()
    if SEEN_JOBS_FILE.exists():
        import json as _j
        seen = set(_j.load(open(SEEN_JOBS_FILE)).get("seen_ids", []))

    jobs = scrape_with_playwright(seen)

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


COMMANDS = {"scrape": cmd_scrape, "run": cmd_run, "status": cmd_status}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: python src/cli.py [{' | '.join(COMMANDS)}]", file=sys.stderr)
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
