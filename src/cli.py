#!/usr/bin/env python3
"""
src/cli.py – Multi-user CLI wrapper for the job-hunt skill.

Commands:
  scrape   [--user-id ID]   Scrape LinkedIn jobs — prints JSON to stdout
  run      --user-id ID     Full pipeline (scrape + tailor + PDF + Discord)
  status   --user-id ID     Today's output summary
  setup    --user-id ID     Interactive first-time user setup

Usage (called by OpenClaw job-hunt skill):
  python src/cli.py scrape
  python src/cli.py run --user-id 970771448320897095
  python src/cli.py status --user-id 970771448320897095
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

# ── Parse --user-id from argv ──────────────────────────────────────────────────
def _parse_user_id() -> str | None:
    """Extract --user-id VALUE from sys.argv. Returns None if not provided."""
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--user-id" and i + 1 < len(args):
            return args[i + 1]
    return None


# ── Commands ───────────────────────────────────────────────────────────────────

def cmd_scrape():
    """Scrape LinkedIn for new jobs (shared pool — not user-specific)."""
    from linkedin_scraper import scrape_with_playwright
    from config.settings import SEEN_JOBS_FILE
    import config.settings as _settings

    cfg_path = PROJECT_ROOT / "config" / "search_config.json"
    cfg = json.load(open(cfg_path))
    preview_limit = cfg.get("max_candidates_preview", 20)
    original_limit = _settings.MAX_JOBS_PER_RUN
    _settings.MAX_JOBS_PER_RUN = preview_limit

    seen: set[str] = set()
    if SEEN_JOBS_FILE.exists():
        seen = set(json.load(open(SEEN_JOBS_FILE)).get("seen_ids", []))

    try:
        jobs = scrape_with_playwright(seen)
    finally:
        _settings.MAX_JOBS_PER_RUN = original_limit

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
    """Run the full pipeline for a specific user."""
    import main
    user_id = _parse_user_id()
    main.run(user_id=user_id)


def cmd_status():
    """Print today's output summary for a specific user (DB first, filesystem fallback)."""
    user_id = _parse_user_id()
    today = date.today().isoformat()
    result = {"date": today, "user_id": user_id, "companies": [], "total": 0, "ok": 0}

    # Try DB first
    db_used = False
    try:
        import db as _db_mod
        if _db_mod.db_available() and user_id:
            rows = _db_mod.get_today_results(user_id)
            if rows is not None:
                for row in rows:
                    result["companies"].append({
                        "name":    row.get("company", ""),
                        "success": bool(row.get("success")),
                        "title":   row.get("title", ""),
                    })
                result["total"] = len(result["companies"])
                result["ok"]    = sum(1 for c in result["companies"] if c["success"])
                db_used = True
    except Exception:
        pass

    # Fallback: scan filesystem
    if not db_used:
        from config.user_config import get_user_output_dir
        today_dir = get_user_output_dir(user_id) / today
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


def cmd_setup():
    """Check if user is set up; print status as JSON."""
    from config.user_config import get_user_dir, user_is_ready

    user_id = _parse_user_id()
    if not user_id:
        print(json.dumps({"error": "missing --user-id"}))
        sys.exit(1)

    user_dir = get_user_dir(user_id)
    profile_path = user_dir / "profile.json"
    resume_path  = user_dir / "resume.html"

    result = {
        "user_id":      user_id,
        "user_dir":     str(user_dir),
        "has_profile":  profile_path.exists(),
        "has_resume":   resume_path.exists(),
        "ready":        user_is_ready(user_id),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


COMMANDS = {
    "scrape": cmd_scrape,
    "run":    cmd_run,
    "status": cmd_status,
    "setup":  cmd_setup,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: python src/cli.py [{' | '.join(COMMANDS)}] [--user-id ID]",
              file=sys.stderr)
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
