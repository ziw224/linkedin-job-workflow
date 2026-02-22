"""
src/notifier.py – Send job-hunt summary to Discord via webhook.
"""
import json
import logging
import os
from datetime import date

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    _HAS_REQUESTS = False

logger = logging.getLogger(__name__)


def send_discord_report(results: list[dict]) -> None:
    """
    results: list of dicts with keys job, html_path, pdf_path, success.
    Sends a formatted message to the Discord webhook.
    """
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        logger.error("DISCORD_WEBHOOK_URL not set in .env")
        return

    today = date.today().strftime("%B %d, %Y")
    ok     = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    if not results:
        content = f"🔍 **Daily Job Hunt** — {today}\nNo new jobs found today. Checking again tomorrow!"
    else:
        lines = [
            f"🔍 **Daily Job Hunt Report** — {today}",
            f"Found **{len(results)}** new job(s) · ✅ {len(ok)} tailored · ❌ {len(failed)} failed",
            "",
        ]
        for i, r in enumerate(results, 1):
            job    = r["job"]
            status = "✅ Resume ready" if r["success"] else "❌ Resume failed"
            cl_ok  = "✅" if r.get("cover_letter") else "❌"
            why_ok = "✅" if r.get("why_company")  else "❌"
            lines += [
                f"**{i}. {job['title']}** @ {job['company']} | {job['location']}",
                f"<{job['url']}>",
                f"{status} · Cover Letter {cl_ok} · Why {job['company']} {why_ok}",
                "",
            ]
        content = "\n".join(lines).strip()

    try:
        import requests
        resp = requests.post(
            webhook_url,
            json={"content": content},
            timeout=15,
        )
        if resp.status_code in (200, 204):
            logger.info("Discord webhook notification sent.")
        else:
            logger.warning(f"Webhook returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Webhook failed: {e}")
